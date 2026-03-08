from __future__ import annotations

from pathlib import Path

import requests

from app.utils.retry import run_with_retry


class Downloader:
    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "paper-watcher/1.0 (+https://github.com)"}
        )

    def get_text(
        self,
        url: str,
        *,
        max_attempts: int,
        base_delay_seconds: float,
        max_delay_seconds: float,
    ) -> str:
        def _request() -> str:
            response = self.session.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
            try:
                return response.content.decode("utf-8")
            except UnicodeDecodeError:
                response.encoding = response.apparent_encoding or response.encoding
                return response.text

        return run_with_retry(
            _request,
            max_attempts=max_attempts,
            base_delay=base_delay_seconds,
            max_delay=max_delay_seconds,
            retry_exceptions=(requests.RequestException,),
        )

    def download_file(
        self,
        url: str,
        target_path: Path,
        *,
        max_attempts: int,
        base_delay_seconds: float,
        max_delay_seconds: float,
        chunk_size: int = 1024 * 256,
    ) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = target_path.with_suffix(target_path.suffix + ".part")

        def _download_once() -> Path:
            existing_size = part_path.stat().st_size if part_path.exists() else 0
            headers = {}
            mode = "wb"
            if existing_size > 0:
                headers["Range"] = f"bytes={existing_size}-"
                mode = "ab"

            response = self.session.get(
                url,
                headers=headers,
                stream=True,
                timeout=self.timeout_seconds,
            )

            if response.status_code == 416 and target_path.exists():
                return target_path
            response.raise_for_status()

            if existing_size > 0 and response.status_code == 200:
                # Remote does not support range; restart from zero.
                mode = "wb"
                existing_size = 0

            with part_path.open(mode) as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)

            part_path.replace(target_path)
            return target_path

        return run_with_retry(
            _download_once,
            max_attempts=max_attempts,
            base_delay=base_delay_seconds,
            max_delay=max_delay_seconds,
            retry_exceptions=(requests.RequestException, OSError),
        )
