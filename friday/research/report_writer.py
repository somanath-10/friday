"""Research report writer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from friday.path_utils import workspace_dir
from friday.research.citations import Citation, format_citation


def reports_dir() -> Path:
    path = workspace_dir() / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_research_report(topic: str, summary: str, citations: list[Citation], *, filename: str = "") -> Path:
    safe_name = filename or "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in topic.lower()).strip("_")
    if not safe_name:
        safe_name = "research_report"
    if not safe_name.endswith(".md"):
        safe_name += ".md"
    target = reports_dir() / safe_name
    body = [
        "---",
        f"topic: {topic}",
        f"created_at: {datetime.now(timezone.utc).isoformat()}",
        "source_urls:",
        *[f"  - {citation.url}" for citation in citations],
        "---",
        "",
        f"# {topic}",
        "",
        summary.strip(),
        "",
        "## Sources",
    ]
    body.extend(format_citation(citation, index) for index, citation in enumerate(citations, start=1))
    target.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
    return target
