"""Local research workflow runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.research.citations import Citation
from friday.research.fetch import fetch_url
from friday.research.report_writer import write_research_report
from friday.research.scrape import extract_relevant_text
from friday.research.search import build_search_trace


@dataclass(frozen=True)
class ResearchResult:
    ok: bool
    topic: str
    message: str
    report_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchRuntime:
    def execute(self, topic: str, *, source_urls: list[str] | None = None, dry_run: bool = False) -> ResearchResult:
        trace = build_search_trace(topic)
        urls = source_urls or []
        if dry_run:
            return ResearchResult(True, topic, "Dry run: would search/fetch sources and write a cited report.", metadata={"trace": trace, "source_urls": urls}, dry_run=True)

        citations: list[Citation] = []
        source_notes: list[str] = []
        for url in urls:
            fetched = fetch_url(url)
            if fetched.ok:
                source_notes.append(extract_relevant_text(fetched.text, max_chars=1500))
                citations.append(Citation(title=url, url=fetched.url, accessed_at=datetime.now(timezone.utc).date().isoformat()))
            else:
                trace.setdefault("fetch_errors", []).append(fetched.to_dict())

        summary = "\n\n".join(note for note in source_notes if note).strip()
        if not summary:
            summary = (
                "No live sources were fetched for this local research run. "
                "Configure a search provider or provide source URLs to generate a fully cited report."
            )
        report = write_research_report(topic, summary, citations)
        return ResearchResult(True, topic, f"Research report saved: {report}", report_path=str(report), metadata={"trace": trace, "sources": [item.to_dict() for item in citations]})
