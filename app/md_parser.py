from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


_BULLET_LINK_RE = re.compile(r"^\s*[-*+]\s*\[([^\]]+)\]\(([^)]+)\)\s*(?:[-:]\s*(.*))?$")
_NUMBER_LINK_RE = re.compile(r"^\s*\d+\.\s*\[([^\]]+)\]\(([^)]+)\)\s*(?:[-:]\s*(.*))?$")
_HEADER_LINK_RE = re.compile(r"^\s{0,3}#{1,6}\s*\[([^\]]+)\]\(([^)]+)\)\s*$")
_DAILY_ARXIV_HEADER_RE = re.compile(
    r"^\s{0,3}#{1,6}\s*\[\d+\]\s*\[([^\]]+)\]\((https?://[^)]+)\)\s*$"
)
_ARXIV_LINK_RE = re.compile(r"https?://arxiv\.org/(?:abs|pdf)/([a-z\-]+/\d{7}|\d{4}\.\d{4,5}(?:v\d+)?)")


@dataclass(slots=True)
class ArticleEntry:
    paper_id: str
    title: str
    summary: str
    url: str
    raw_block: str


def _make_paper_id(title: str, url: str) -> str:
    payload = f"{title.strip()}||{url.strip()}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _pick_summary(block_lines: list[str]) -> str:
    for line in block_lines:
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith("tl;dr:") or lowered.startswith("tl;dr：") or lowered.startswith("tldr:"):
            if ":" in stripped:
                return stripped.split(":", 1)[1].strip()
            if "：" in stripped:
                return stripped.split("：", 1)[1].strip()
            return stripped

    for line in block_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("<") or stripped.startswith("*"):
            continue
        if stripped.lower().startswith("main category:"):
            continue
        if stripped.lower().startswith("motivation:"):
            continue
        if stripped.lower().startswith("method:"):
            continue
        if stripped.lower().startswith("result:"):
            continue
        if stripped.lower().startswith("conclusion:"):
            continue
        if stripped.lower().startswith("abstract:"):
            continue
        return stripped[:500]
    return ""


def _parse_daily_arxiv_style(md_text: str) -> list[ArticleEntry]:
    lines = md_text.splitlines()
    entries: list[ArticleEntry] = []
    current_title: str | None = None
    current_url: str | None = None
    block_lines: list[str] = []

    def flush_current() -> None:
        nonlocal current_title, current_url, block_lines
        if not current_title or not current_url:
            current_title = None
            current_url = None
            block_lines = []
            return
        summary = _pick_summary(block_lines)
        raw_block = "\n".join(block_lines).strip()
        paper_id = _make_paper_id(current_title, current_url)
        entries.append(
            ArticleEntry(
                paper_id=paper_id,
                title=current_title,
                summary=summary,
                url=current_url,
                raw_block=raw_block,
            )
        )
        current_title = None
        current_url = None
        block_lines = []

    for line in lines:
        match = _DAILY_ARXIV_HEADER_RE.match(line)
        if match:
            flush_current()
            current_title = match.group(1).strip()
            current_url = match.group(2).strip()
            block_lines = [line]
            continue
        if current_title is not None:
            block_lines.append(line)

    flush_current()
    return entries


def _parse_generic_style(md_text: str) -> list[ArticleEntry]:
    lines = md_text.splitlines()
    entries: list[ArticleEntry] = []
    current: dict[str, str] | None = None
    summary_lines: list[str] = []
    raw_lines: list[str] = []

    def flush_current() -> None:
        nonlocal current, summary_lines, raw_lines
        if not current:
            return
        summary = " ".join(s.strip() for s in summary_lines if s.strip()).strip()
        raw_block = "\n".join(raw_lines).strip()
        paper_id = _make_paper_id(current["title"], current["url"])
        entries.append(
            ArticleEntry(
                paper_id=paper_id,
                title=current["title"].strip(),
                summary=summary[:500],
                url=current["url"].strip(),
                raw_block=raw_block,
            )
        )
        current = None
        summary_lines = []
        raw_lines = []

    for line in lines:
        candidate = None
        for pattern in (_BULLET_LINK_RE, _NUMBER_LINK_RE, _HEADER_LINK_RE):
            match = pattern.match(line)
            if match:
                title = match.group(1).strip()
                url = match.group(2).strip()
                inline_desc = (match.group(3) or "").strip() if len(match.groups()) >= 3 else ""
                candidate = {"title": title, "url": url, "inline_desc": inline_desc}
                break

        if candidate:
            flush_current()
            current = {"title": candidate["title"], "url": candidate["url"]}
            if candidate["inline_desc"]:
                summary_lines.append(candidate["inline_desc"])
            raw_lines.append(line)
            continue

        if current is not None:
            if line.startswith("#"):
                flush_current()
                continue
            raw_lines.append(line)
            if line.strip():
                summary_lines.append(line.strip())

    flush_current()
    return entries


def parse_markdown(md_text: str) -> list[ArticleEntry]:
    entries = _parse_daily_arxiv_style(md_text)
    if not entries:
        entries = _parse_generic_style(md_text)

    uniq: dict[str, ArticleEntry] = {}
    for item in entries:
        uniq[item.paper_id] = item
    return list(uniq.values())


def extract_arxiv_id_from_text(text: str) -> str | None:
    match = _ARXIV_LINK_RE.search(text or "")
    if not match:
        return None
    return match.group(1)
