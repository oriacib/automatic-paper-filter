from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from app.state_db import StateDB
from app.utils.dates import format_date, iter_dates
from app.utils.file_ops import atomic_write_text, read_json


def _build_digest_content(start_date: date, end_date: date, medium_items: list[dict]) -> str:
    lines: list[str] = [
        f"# Medium Relevance Digest ({format_date(start_date)} to {format_date(end_date)})",
        "",
        f"Total items: {len(medium_items)}",
        "",
    ]
    for item in medium_items:
        lines.append(f"## {item['source_date']} - {item['title']}")
        lines.append(f"- Score: {item['combined_score']:.3f}")
        if item.get("url"):
            lines.append(f"- URL: {item['url']}")
        if item.get("summary"):
            lines.append(f"- Summary: {item['summary']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def generate_medium_digest(
    processed_dir: Path,
    digest_dir: Path,
    state_db: StateDB,
    start_date: date,
    end_date: date,
) -> tuple[Path, bool]:
    medium_items: list[dict] = []
    seen_ids: set[str] = set()
    for d in iter_dates(start_date, end_date):
        date_str = format_date(d)
        meta_path = processed_dir / date_str / "metadata.json"
        payload = read_json(meta_path, default={})
        for paper in payload.get("papers", []):
            if paper.get("relevance") != "medium":
                continue
            pid = str(paper.get("paper_id", ""))
            if pid and pid in seen_ids:
                continue
            if pid:
                seen_ids.add(pid)
            paper["source_date"] = date_str
            medium_items.append(paper)

    digest_dir.mkdir(parents=True, exist_ok=True)
    name = f"{format_date(start_date)}_to_{format_date(end_date)}.md"
    output_path = digest_dir / name
    content = _build_digest_content(start_date, end_date, medium_items)
    checksum = hashlib.sha1(content.encode("utf-8")).hexdigest()
    window_key = name[:-3]
    prev_checksum = state_db.get_digest_checksum(window_key)
    changed = checksum != prev_checksum or not output_path.exists()
    if changed:
        atomic_write_text(output_path, content)
        state_db.upsert_digest(window_key, str(output_path), checksum)
    return output_path, changed
