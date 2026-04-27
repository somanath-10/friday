"""Document reading helpers with graceful optional dependency handling."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def read_document(path: str | Path, *, max_chars: int = 12000) -> str:
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix == ".pdf":
        try:
            import pypdf  # type: ignore
        except Exception as exc:
            raise RuntimeError("PDF reading requires pypdf.") from exc
        reader = pypdf.PdfReader(str(target))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        return text[:max_chars]
    if suffix == ".json":
        return json.dumps(json.loads(target.read_text(encoding="utf-8")), indent=2)[:max_chars]
    if suffix == ".csv":
        with target.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        return "\n".join(", ".join(row) for row in rows[:200])[:max_chars]
    return target.read_text(encoding="utf-8", errors="replace")[:max_chars]
