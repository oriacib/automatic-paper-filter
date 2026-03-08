from __future__ import annotations

import re
from datetime import date
from datetime import timedelta
from pathlib import Path

import requests

from app.config import AppConfig
from app.downloader import Downloader
from app.state_db import StateDB
from app.utils.dates import format_date, iter_dates, parse_date
from app.utils.file_ops import atomic_write_text, ensure_dir


class GitHubSync:
    def __init__(self, config: AppConfig, state_db: StateDB, downloader: Downloader, logger) -> None:
        self.config = config
        self.state_db = state_db
        self.downloader = downloader
        self.logger = logger
        ensure_dir(config.raw_md_dir)

    def _template_parts(self) -> tuple[str, str, str]:
        template = self.config.github.path_template.strip().lstrip("/")
        if "{date}" not in template:
            raise ValueError("github.path_template must include {date}")
        file_name_template = template.split("/")[-1]
        dir_path = "/".join(template.split("/")[:-1])
        prefix, suffix = file_name_template.split("{date}", 1)
        return dir_path, prefix, suffix

    def build_raw_url(self, date_str: str) -> str:
        gh = self.config.github
        if gh.raw_url_template:
            return gh.raw_url_template.format(
                owner=gh.owner,
                repo=gh.repo,
                branch=gh.branch,
                date=date_str,
            )
        path = gh.path_template.format(date=date_str).lstrip("/")
        return f"https://raw.githubusercontent.com/{gh.owner}/{gh.repo}/{gh.branch}/{path}"

    def local_path_for_date(self, date_str: str) -> Path:
        return self.config.raw_md_dir / f"{date_str}.md"

    def _extract_date_from_name(self, file_name: str, prefix: str, suffix: str) -> str | None:
        if not file_name.startswith(prefix) or not file_name.endswith(suffix):
            return None
        candidate = file_name[len(prefix) : len(file_name) - len(suffix) if suffix else None]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
            return None
        return candidate

    def _list_remote_dates_via_api(self) -> list[str]:
        gh = self.config.github
        dir_path, prefix, suffix = self._template_parts()
        endpoint = f"https://api.github.com/repos/{gh.owner}/{gh.repo}/contents/{dir_path}?ref={gh.branch}"
        headers = {"Accept": "application/vnd.github+json"}
        if gh.token:
            headers["Authorization"] = f"Bearer {gh.token}"
        response = requests.get(endpoint, headers=headers, timeout=gh.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        dates: list[str] = []
        for item in payload:
            if item.get("type") != "file":
                continue
            name = str(item.get("name", ""))
            parsed = self._extract_date_from_name(name, prefix, suffix)
            if parsed:
                dates.append(parsed)
        return sorted(set(dates))

    def _list_remote_dates_via_html(self) -> list[str]:
        gh = self.config.github
        dir_path, prefix, suffix = self._template_parts()
        tree_url = f"https://github.com/{gh.owner}/{gh.repo}/tree/{gh.branch}/{dir_path}".rstrip("/")
        html = self.downloader.get_text(
            tree_url,
            max_attempts=self.config.sync.max_attempts,
            base_delay_seconds=self.config.sync.base_delay_seconds,
            max_delay_seconds=self.config.sync.max_delay_seconds,
        )

        dates: list[str] = []

        # Wider fallback match because GitHub HTML can render partial file rows.
        if dir_path:
            path_pattern = re.compile(
                rf"{re.escape(dir_path)}/{re.escape(prefix)}(\d{{4}}-\d{{2}}-\d{{2}}){re.escape(suffix)}"
            )
            for match in path_pattern.finditer(html):
                dates.append(match.group(1))

        # Extra fallback on blob links in case page structure changes.
        dir_part = f"/{dir_path}/" if dir_path else "/"
        blob_pattern = re.compile(
            rf"/{re.escape(gh.owner)}/{re.escape(gh.repo)}/blob/{re.escape(gh.branch)}{re.escape(dir_part)}([^\"?#<>/]+)"
        )
        for match in blob_pattern.finditer(html):
            parsed = self._extract_date_from_name(match.group(1), prefix, suffix)
            if parsed:
                dates.append(parsed)
        return sorted(set(dates))

    def list_remote_dates(self) -> list[str]:
        try:
            dates = self._list_remote_dates_via_api()
            if dates:
                return dates
        except Exception as exc:
            self.logger.warning("github api listing failed, fallback to html: %s", exc)
        dates = self._list_remote_dates_via_html()
        return dates

    def select_unsynced_remote_dates(
        self,
        start: str | None = None,
        end: str | None = None,
        remote_dates: list[str] | None = None,
    ) -> list[str]:
        remote_dates = remote_dates if remote_dates is not None else self.list_remote_dates()
        if not remote_dates:
            return []

        start_date = parse_date(start) if start else None
        end_date = parse_date(end) if end else None
        if start_date is None and end_date is None and self.config.sync.catch_up_from_last_success:
            last_success = self.state_db.latest_success_fetch_date()
            if last_success:
                start_date = parse_date(last_success) + timedelta(days=1)
            else:
                latest_remote = parse_date(remote_dates[-1])
                window = max(1, int(self.config.sync.lookback_days))
                start_date = latest_remote - timedelta(days=window - 1)

        selected: list[str] = []
        for d_str in remote_dates:
            d = parse_date(d_str)
            if start_date and d < start_date:
                continue
            if end_date and d > end_date:
                continue
            local_path = self.local_path_for_date(d_str)
            if local_path.exists():
                if not self.state_db.was_date_synced(d_str):
                    self.state_db.mark_date_sync(d_str, "success", str(local_path), None)
                continue
            if self.state_db.was_date_synced(d_str):
                continue
            selected.append(d_str)
        return selected

    def sync_dates(self, date_list: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for date_str in date_list:
            local_path = self.local_path_for_date(date_str)
            already_synced = self.state_db.was_date_synced(date_str)
            if already_synced and local_path.exists():
                result[date_str] = "skipped"
                continue
            if local_path.exists():
                self.state_db.mark_date_sync(date_str, "success", str(local_path), None)
                result[date_str] = "skipped"
                continue

            url = self.build_raw_url(date_str)
            try:
                content = self.downloader.get_text(
                    url,
                    max_attempts=self.config.sync.max_attempts,
                    base_delay_seconds=self.config.sync.base_delay_seconds,
                    max_delay_seconds=self.config.sync.max_delay_seconds,
                )
                atomic_write_text(local_path, content)
                self.state_db.mark_date_sync(date_str, "success", str(local_path), None)
                self.logger.info("synced %s from %s", date_str, url)
                result[date_str] = "synced"
            except Exception as exc:
                self.state_db.mark_date_sync(date_str, "failed", str(local_path), str(exc))
                self.logger.warning("sync failed for %s: %s", date_str, exc)
                result[date_str] = "failed"
        return result

    def sync_date_range(self, start_date: date, end_date: date) -> dict[str, str]:
        date_list = [format_date(d) for d in iter_dates(start_date, end_date)]
        try:
            remote_set = set(self.list_remote_dates())
            if remote_set:
                date_list = [d for d in date_list if d in remote_set]
        except Exception as exc:
            self.logger.warning("range listing failed, fallback to direct date fetch: %s", exc)
        return self.sync_dates(date_list)
