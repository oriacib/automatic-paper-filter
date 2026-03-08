from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    ensure_dir(path.parent)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding=encoding, newline="\n")
    tmp_path.replace(path)


def atomic_write_json(path: Path, payload: Any) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    atomic_write_text(path, content)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))
