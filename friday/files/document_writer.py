"""Document writing helpers for local reports."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def write_text_document(path: str | Path, content: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def write_json_document(path: str | Path, payload: Any) -> Path:
    return write_text_document(path, json.dumps(payload, indent=2, ensure_ascii=False))


def write_csv_document(path: str | Path, rows: list[list[Any]]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)
    return target


def write_markdown_report(path: str | Path, title: str, body: str, metadata: dict[str, Any] | None = None) -> Path:
    meta = ""
    if metadata:
        meta = "---\n" + "\n".join(f"{key}: {value}" for key, value in metadata.items()) + "\n---\n\n"
    return write_text_document(path, f"{meta}# {title}\n\n{body.rstrip()}\n")
