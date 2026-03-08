from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests

from app.downloader import Downloader

ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/)?([a-z\-]+/\d{7}|\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    cleaned = cleaned.replace(" ", "_")
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned:
        return "paper"
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    if cleaned.upper() in reserved:
        cleaned = f"_{cleaned}"
    return cleaned[:150]


def build_title_pdf_name(
    title: str,
    arxiv_id: str,
    target_dir: Path,
    date_prefix: str | None = None,
) -> str:
    base = sanitize_filename(title)
    if date_prefix:
        base = sanitize_filename(f"{date_prefix}_{base}")
    primary = f"{base}.pdf"
    primary_path = target_dir / primary
    if not primary_path.exists():
        return primary

    safe_id = sanitize_filename(arxiv_id.replace("/", "_"))
    fallback = f"{base}_{safe_id}.pdf"
    fallback_path = target_dir / fallback
    if not fallback_path.exists():
        return fallback

    idx = 2
    while True:
        candidate = f"{base}_{safe_id}_{idx}.pdf"
        if not (target_dir / candidate).exists():
            return candidate
        idx += 1


class ArxivClient:
    def __init__(self, timeout_seconds: int = 20) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "paper-watcher/1.0 (+https://github.com)"}
        )

    def extract_arxiv_id(self, text: str) -> str | None:
        if not text:
            return None
        match = ARXIV_ID_RE.search(text)
        return match.group(1) if match else None

    def fetch_metadata(self, arxiv_id: str) -> dict[str, Any]:
        url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
        response = self.session.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            raise ValueError(f"arXiv metadata not found for {arxiv_id}")

        title = (entry.findtext("atom:title", "", ns) or "").strip().replace("\n", " ")
        summary = (entry.findtext("atom:summary", "", ns) or "").strip().replace("\n", " ")
        published = (entry.findtext("atom:published", "", ns) or "").strip()
        authors = [a.findtext("atom:name", "", ns) or "" for a in entry.findall("atom:author", ns)]
        primary_category = ""
        primary_node = entry.find("{http://arxiv.org/schemas/atom}primary_category")
        if primary_node is not None:
            primary_category = primary_node.attrib.get("term", "")

        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        return {
            "arxiv_id": arxiv_id,
            "title": title,
            "summary": summary,
            "published": published,
            "authors": authors,
            "primary_category": primary_category,
            "pdf_url": pdf_url,
        }

    def download_pdf(
        self,
        arxiv_id: str,
        title: str,
        target_dir: Path,
        downloader: Downloader,
        *,
        max_attempts: int,
        base_delay_seconds: float,
        max_delay_seconds: float,
    ) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = build_title_pdf_name(title=title, arxiv_id=arxiv_id, target_dir=target_dir)
        target_path = target_dir / safe_name
        if target_path.exists():
            return target_path

        return downloader.download_file(
            f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            target_path,
            max_attempts=max_attempts,
            base_delay_seconds=base_delay_seconds,
            max_delay_seconds=max_delay_seconds,
        )
