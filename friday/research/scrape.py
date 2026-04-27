"""Lightweight page text extraction."""

from __future__ import annotations

from html.parser import HTMLParser


class _TextParser(HTMLParser):
    ignored = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.ignored:
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.ignored:
            self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if self.depth:
            return
        cleaned = " ".join(data.split())
        if cleaned:
            self.parts.append(cleaned)


def extract_relevant_text(html: str, *, max_chars: int = 12000) -> str:
    parser = _TextParser()
    parser.feed(html)
    return " ".join(parser.parts)[:max_chars]
