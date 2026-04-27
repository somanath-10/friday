"""DOM snapshot parsing and indexed element generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin


@dataclass(frozen=True)
class DomElement:
    index: int
    tag: str
    label: str
    href: str = ""
    role: str = ""
    input_type: str = ""
    name: str = ""
    disabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DomSnapshot:
    title: str
    text: str
    elements: list[DomElement]
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "text": self.text,
            "url": self.url,
            "elements": [element.to_dict() for element in self.elements],
        }


class _SnapshotParser(HTMLParser):
    interactive_tags = {"a", "button", "input", "textarea", "select"}
    void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, base_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.elements: list[DomElement] = []
        self._in_title = False
        self._interactive_stack: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        role = attr_map.get("role", "")
        if tag in self.interactive_tags or role in {"button", "link", "tab", "menuitem"}:
            self._interactive_stack.append(
                {
                    "tag": tag,
                    "role": role,
                    "href": urljoin(self.base_url, attr_map.get("href", "")) if attr_map.get("href") else "",
                    "input_type": attr_map.get("type", ""),
                    "name": attr_map.get("name", ""),
                    "disabled": "disabled" in attr_map or attr_map.get("aria-disabled") == "true",
                    "label_parts": [
                        attr_map.get("aria-label", ""),
                        attr_map.get("placeholder", ""),
                        attr_map.get("title", ""),
                        attr_map.get("value", ""),
                    ],
                }
            )
            if tag in self.void_tags:
                self._finalize_interactive(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if self._interactive_stack and self._interactive_stack[-1]["tag"] == tag:
            self._finalize_interactive(tag)

    def handle_data(self, data: str) -> None:
        cleaned = _collapse(data)
        if not cleaned:
            return
        if self._in_title:
            self.title_parts.append(cleaned)
        self.text_parts.append(cleaned)
        for item in self._interactive_stack:
            item["label_parts"].append(cleaned)

    def _finalize_interactive(self, tag: str) -> None:
        if not self._interactive_stack or self._interactive_stack[-1]["tag"] != tag:
            return
        item = self._interactive_stack.pop()
        label = _collapse(" ".join(str(part) for part in item.pop("label_parts", []) if part))
        if label or item.get("href") or item.get("name"):
            self.elements.append(
                DomElement(
                    index=len(self.elements) + 1,
                    tag=item["tag"],
                    label=label or item.get("href") or item.get("name") or "(unlabeled)",
                    href=item.get("href", ""),
                    role=item.get("role", ""),
                    input_type=item.get("input_type", ""),
                    name=item.get("name", ""),
                    disabled=bool(item.get("disabled")),
                )
            )


def _collapse(text: str) -> str:
    return " ".join((text or "").split())


def parse_html_snapshot(html: str, *, base_url: str = "") -> DomSnapshot:
    parser = _SnapshotParser(base_url)
    parser.feed(html)
    text = _collapse(" ".join(parser.text_parts))
    title = _collapse(" ".join(parser.title_parts)) or text[:120]
    return DomSnapshot(title=title, text=text, elements=parser.elements, url=base_url)


def format_indexed_elements(snapshot: DomSnapshot, limit: int = 30) -> str:
    lines = [f"Page title: {snapshot.title}", f"URL: {snapshot.url}", f"Interactive elements: {len(snapshot.elements)} total"]
    for item in snapshot.elements[: max(1, limit)]:
        meta = []
        if item.role:
            meta.append(f"role={item.role}")
        if item.input_type:
            meta.append(f"type={item.input_type}")
        if item.disabled:
            meta.append("disabled")
        suffix = f" ({', '.join(meta)})" if meta else ""
        target = f" -> {item.href}" if item.href else ""
        lines.append(f"[{item.index}] {item.tag}{suffix} :: {item.label}{target}")
    return "\n".join(lines)
