"""Patch helpers for code edits."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from friday.files.backup import create_backup


@dataclass(frozen=True)
class PatchResult:
    ok: bool
    message: str
    path: str = ""
    backup_path: str = ""
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def replace_file_text(path: str | Path, old: str, new: str, *, dry_run: bool = True) -> PatchResult:
    target = Path(path)
    if not target.exists():
        return PatchResult(False, f"File not found: {target}", path=str(target), dry_run=dry_run)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        return PatchResult(False, "Requested text was not found.", path=str(target), dry_run=dry_run)
    if dry_run:
        return PatchResult(True, f"Dry run: would patch {target}", path=str(target), dry_run=True)
    backup = create_backup(target)
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return PatchResult(True, f"Patched {target}", path=str(target), backup_path=str(backup))
