"""
Browser automation tools for FRIDAY.

This module prefers a persistent Playwright browser session for rich browser
automation. On Windows hosts where Playwright cannot start because the OS
blocks asyncio pipe creation, it falls back to an HTTP-backed page session so
navigation, reading, and basic link-following still work.
"""

from __future__ import annotations

import asyncio
import os
import re
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import httpx

from friday.core.permissions import (
    authorize_tool_call,
    format_permission_response,
    record_tool_result,
)

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_playwright = None
_browser = None
_page = None
_browser_backend = "playwright"
_http_client: httpx.AsyncClient | None = None
_http_state: dict | None = None
_http_backend_reason = ""


def _require_playwright() -> None:
    if async_playwright is None:
        raise RuntimeError(
            "Playwright is not installed. Run `uv sync` and `playwright install chromium` before using browser tools."
        )


def _browser_headless() -> bool:
    value = os.environ.get("FRIDAY_BROWSER_HEADLESS", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text or "")).strip()


def _interactive_elements_script() -> str:
    return r"""() => {
  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.visibility !== 'hidden' &&
      style.display !== 'none';
  };

  const selectors = [
    'a',
    'button',
    'input',
    'textarea',
    'select',
    '[role="button"]',
    '[role="link"]',
    '[role="menuitem"]',
    '[role="tab"]',
    '[contenteditable="true"]',
    '[tabindex]'
  ];

  const candidates = Array.from(document.querySelectorAll(selectors.join(',')));
  const items = [];

  for (const el of candidates) {
    if (!isVisible(el)) continue;
    const rect = el.getBoundingClientRect();
    const text = (
      el.innerText ||
      el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') ||
      el.getAttribute('title') ||
      el.getAttribute('name') ||
      el.getAttribute('value') ||
      ''
    ).replace(/\s+/g, ' ').trim();

    if (!text && !['input', 'textarea', 'select'].includes(el.tagName.toLowerCase())) {
      continue;
    }

    items.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      text: text.slice(0, 160),
      ariaLabel: (el.getAttribute('aria-label') || '').slice(0, 120),
      placeholder: (el.getAttribute('placeholder') || '').slice(0, 120),
      title: (el.getAttribute('title') || '').slice(0, 120),
      id: (el.id || '').slice(0, 120),
      name: (el.getAttribute('name') || '').slice(0, 120),
      type: (el.getAttribute('type') || '').slice(0, 60),
      href: (el.getAttribute('href') || '').slice(0, 200),
      disabled: !!el.disabled,
      x: Math.round(rect.left + rect.width / 2),
      y: Math.round(rect.top + rect.height / 2),
      width: Math.round(rect.width),
      height: Math.round(rect.height)
    });
  }
  return items;
}"""


def _grid_dashboard_html(title: str, urls: list[str]) -> str:
    safe_title = escape(title)

    if len(urls) <= 2:
        grid_css = "grid-template-columns: 1fr 1fr;"
    elif len(urls) <= 4:
        grid_css = "grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr;"
    else:
        grid_css = "grid-template-columns: 1fr 1fr 1fr; grid-template-rows: 1fr 1fr;"

    frame_markup: list[str] = []
    for url in urls:
        safe_url = escape(url, quote=True)
        frame_markup.append(
            '<div class="frame-container">'
            f'<div class="frame-title">{safe_url}</div>'
            f'<iframe src="{safe_url}" sandbox="allow-scripts allow-same-origin allow-forms allow-popups"></iframe>'
            "</div>"
        )

    iframes_html = "".join(frame_markup)
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>{safe_title}</title>
    <style>
        body, html {{ margin: 0; padding: 0; height: 100%; font-family: system-ui, sans-serif; background: #081018; color: #fff; overflow: hidden; }}
        .header {{ padding: 12px 20px; background: rgba(12, 28, 42, 0.96); border-bottom: 1px solid rgba(151, 186, 214, 0.16); display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }}
        .header h1 {{ margin: 0; font-size: 1.2rem; background: linear-gradient(135deg, #2ad1be, #ff7b47); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .pulse {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #2ad1be; margin-right: 10px; animation: pulse 1.5s infinite; }}
        @keyframes pulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(42, 209, 190, 0.6); }} 70% {{ box-shadow: 0 0 0 10px rgba(42, 209, 190, 0); }} 100% {{ box-shadow: 0 0 0 0 rgba(42, 209, 190, 0); }} }}
        .grid {{ display: grid; {grid_css} gap: 2px; height: calc(100vh - 50px); background: #000; }}
        .frame-container {{ display: flex; flex-direction: column; background: #111; position: relative; }}
        .frame-title {{ font-size: 0.75rem; padding: 4px 8px; background: #1a2530; color: #96abc1; border-bottom: 1px solid #333; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        iframe {{ border: none; width: 100%; flex-grow: 1; background: #fff; }}
    </style>
</head>
<body>
    <div class="header">
        <h1><span class="pulse"></span>Deep Research: {safe_title}</h1>
        <div style="font-size: 0.8rem; color: #96abc1;">Analyzing {len(urls)} sources simultaneously...</div>
    </div>
    <div class="grid">
        {iframes_html}
    </div>
</body>
</html>"""


class _HTMLSnapshotParser(HTMLParser):
    _ignored_tags = {"script", "style", "noscript"}
    _interactive_tags = {"a", "button", "input", "textarea", "select"}
    _content_tags = {"h1", "h2", "h3", "p", "li", "a", "button", "label"}
    _void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.first_heading = ""
        self.visible_text_parts: list[str] = []
        self.content_lines: list[str] = []
        self.elements: list[dict] = []
        self._ignored_depth = 0
        self._in_title = False
        self._heading_stack: list[list[str]] = []
        self._interactive_stack: list[dict] = []
        self._content_stack: list[dict] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._ignored_tags:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return

        attr_map = {key: value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        if tag in {"h1", "h2", "h3"}:
            self._heading_stack.append([])
        if tag in self._content_tags:
            self._content_stack.append({"tag": tag, "parts": []})
        if tag in self._interactive_tags or attr_map.get("role") in {"button", "link", "menuitem", "tab"} or "tabindex" in attr_map:
            element = {
                "tag": tag,
                "role": attr_map.get("role", ""),
                "text": "",
                "ariaLabel": _collapse_whitespace(attr_map.get("aria-label", ""))[:120],
                "placeholder": _collapse_whitespace(attr_map.get("placeholder", ""))[:120],
                "title": _collapse_whitespace(attr_map.get("title", ""))[:120],
                "id": _collapse_whitespace(attr_map.get("id", ""))[:120],
                "name": _collapse_whitespace(attr_map.get("name", ""))[:120],
                "type": _collapse_whitespace(attr_map.get("type", ""))[:60],
                "href": urljoin(self.base_url, attr_map.get("href", "")) if attr_map.get("href") else "",
                "disabled": (
                    "disabled" in attr_map
                    or _collapse_whitespace(attr_map.get("aria-disabled", "")).lower() == "true"
                ),
                "_parts": [],
            }
            self._interactive_stack.append(element)
            if tag in self._void_tags:
                self._finalize_interactive(tag)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._void_tags:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._ignored_tags:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth:
            return

        if tag == "title":
            self._in_title = False
        if tag in {"h1", "h2", "h3"} and self._heading_stack:
            parts = self._heading_stack.pop()
            heading = _collapse_whitespace(" ".join(parts))
            if heading and not self.first_heading:
                self.first_heading = heading
        if self._content_stack and self._content_stack[-1]["tag"] == tag:
            item = self._content_stack.pop()
            text = _collapse_whitespace(" ".join(item["parts"]))
            if text:
                line = f"{item['tag'].upper()} | {text[:200]}"
                if line not in self.content_lines:
                    self.content_lines.append(line)
        if self._interactive_stack and self._interactive_stack[-1]["tag"] == tag:
            self._finalize_interactive(tag)

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self.title_parts.append(data)

        cleaned = _collapse_whitespace(data)
        if not cleaned:
            return

        self.visible_text_parts.append(cleaned)
        for heading in self._heading_stack:
            heading.append(cleaned)
        for content_item in self._content_stack:
            content_item["parts"].append(cleaned)
        for element in self._interactive_stack:
            element["_parts"].append(cleaned)

    def snapshot(self) -> dict:
        text = _collapse_whitespace(" ".join(self.visible_text_parts))
        title = _collapse_whitespace(" ".join(self.title_parts))
        if not title:
            title = self.first_heading or (text[:120] if text else "")

        if not self.content_lines and text:
            self.content_lines.append(f"TEXT | {text[:4000]}")

        return {
            "title": title,
            "content": "\n".join(self.content_lines)[:4000],
            "text": text[:12000],
            "elements": self.elements,
        }

    def _finalize_interactive(self, tag: str) -> None:
        if not self._interactive_stack:
            return
        element = self._interactive_stack.pop()
        if element.get("tag") != tag:
            return

        element["text"] = _collapse_whitespace(" ".join(element.pop("_parts", [])))[:160]
        if (
            element.get("text")
            or element.get("ariaLabel")
            or element.get("placeholder")
            or element.get("title")
            or element.get("name")
            or element.get("id")
            or element.get("href")
        ):
            element["index"] = len(self.elements) + 1
            self.elements.append(element)


def _should_use_http_fallback(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        isinstance(exc, PermissionError)
        or "winerror 5" in message
        or "access is denied" in message
        or "playwright is not installed" in message
    )


async def _ensure_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=20,
            headers=HEADERS,
        )
    return _http_client


def _activate_http_fallback(reason: Exception | str) -> None:
    global _browser_backend, _http_backend_reason
    _browser_backend = "http"
    _http_backend_reason = str(reason)


async def _build_http_state(url: str, response: httpx.Response) -> dict:
    parser = _HTMLSnapshotParser(str(response.url))
    parser.feed(response.text)
    snapshot = parser.snapshot()
    return {
        "backend": "http",
        "reason": _http_backend_reason,
        "url": str(response.url),
        "requested_url": url,
        "status_code": response.status_code,
        "html": response.text,
        "title": snapshot["title"] or str(response.url),
        "text": snapshot["text"],
        "content": snapshot["content"],
        "elements": snapshot["elements"],
    }


async def _http_navigate(url: str) -> dict:
    global _http_state
    client = await _ensure_http_client()
    response = await client.get(url)
    response.raise_for_status()
    _http_state = await _build_http_state(url, response)
    return _http_state


async def _http_refresh() -> dict:
    if not _http_state or not _http_state.get("url"):
        raise RuntimeError("No HTTP browser page is loaded yet.")
    return await _http_navigate(_http_state["url"])


def _http_element_label(item: dict) -> str:
    return (
        item.get("text")
        or item.get("ariaLabel")
        or item.get("placeholder")
        or item.get("title")
        or item.get("name")
        or item.get("id")
        or item.get("href")
        or "(unlabeled)"
    )


def _http_state_text(state: dict, limit: int = 30) -> str:
    elements = state.get("elements", [])
    visible = elements[: max(1, limit)]
    lines = [
        "Browser backend: HTTP fallback",
        f"Page title: {state.get('title', '')}",
        f"URL: {state.get('url', '')}",
        f"Interactive elements: {len(elements)} total",
    ]
    if state.get("reason"):
        lines.append(f"Fallback reason: {state['reason']}")

    for item in visible:
        meta = []
        if item.get("role"):
            meta.append(f"role={item['role']}")
        if item.get("type"):
            meta.append(f"type={item['type']}")
        if item.get("disabled"):
            meta.append("disabled")
        meta_part = f" ({', '.join(meta)})" if meta else ""
        label = _http_element_label(item)
        href = item.get("href")
        suffix = f" -> {href}" if href and href != label else ""
        lines.append(f"[{item['index']}] {item.get('tag', '?')}{meta_part} :: {label}{suffix}")
    return "\n".join(lines)


def _http_find_element_by_text(state: dict, text: str, exact: bool) -> dict | None:
    needle = text.strip()
    if not needle:
        return None
    lowered = needle.lower()
    for item in state.get("elements", []):
        haystack = _http_element_label(item)
        if exact:
            if haystack == needle:
                return item
        elif lowered in haystack.lower():
            return item
    return None


async def _get_page():
    global _playwright, _browser, _page
    if _browser_backend == "http":
        raise RuntimeError("Playwright browser session is unavailable while HTTP fallback is active.")
    if not _page:
        try:
            _require_playwright()
            if not _playwright:
                _playwright = await async_playwright().start()
            if not _browser:
                downloads_dir = os.environ.get("FRIDAY_DOWNLOADS_DIR", str(Path.home() / "Downloads"))
                _browser = await _playwright.chromium.launch(
                    headless=_browser_headless(),
                    downloads_path=downloads_dir,
                )
            _page = await _browser.new_page(accept_downloads=True)

            async def strip_frame_headers(route):
                try:
                    response = await route.fetch()
                    headers = {k: v for k, v in response.headers.items() if k.lower() not in ["x-frame-options", "content-security-policy"]}
                    await route.fulfill(response=response, headers=headers)
                except Exception:
                    await route.continue_()

            await _page.route("**/*", strip_frame_headers)
        except Exception as exc:
            if _should_use_http_fallback(exc):
                _activate_http_fallback(exc)
            raise
    return _page


async def _get_interactive_elements(page) -> list[dict]:
    elements = await page.evaluate(_interactive_elements_script())
    if not isinstance(elements, list):
        return []

    cleaned: list[dict] = []
    for index, item in enumerate(elements, start=1):
        if not isinstance(item, dict):
            continue
        record = dict(item)
        record["index"] = index
        cleaned.append(record)
    return cleaned


async def _browser_state_text(page, limit: int = 30) -> str:
    title = await page.title()
    url = page.url
    elements = await _get_interactive_elements(page)
    visible = elements[: max(1, limit)]
    lines = [
        f"Page title: {title}",
        f"URL: {url}",
        f"Interactive elements: {len(elements)} total",
    ]

    for item in visible:
        label = (
            item.get("text")
            or item.get("ariaLabel")
            or item.get("placeholder")
            or item.get("title")
            or item.get("name")
            or item.get("id")
            or item.get("href")
            or "(unlabeled)"
        )
        meta = []
        if item.get("role"):
            meta.append(f"role={item['role']}")
        if item.get("type"):
            meta.append(f"type={item['type']}")
        if item.get("disabled"):
            meta.append("disabled")
        meta_part = f" ({', '.join(meta)})" if meta else ""
        lines.append(
            f"[{item['index']}] {item.get('tag', '?')}{meta_part} :: {label} @ ({item.get('x')},{item.get('y')}) size {item.get('width')}x{item.get('height')}"
        )
    return "\n".join(lines)


async def _click_interactive_index(page, index: int) -> dict:
    script = r"""([targetIndex]) => {
  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.visibility !== 'hidden' &&
      style.display !== 'none';
  };

  const selectors = [
    'a',
    'button',
    'input',
    'textarea',
    'select',
    '[role="button"]',
    '[role="link"]',
    '[role="menuitem"]',
    '[role="tab"]',
    '[contenteditable="true"]',
    '[tabindex]'
  ];

  const candidates = Array.from(document.querySelectorAll(selectors.join(','))).filter(isVisible);
  const el = candidates[targetIndex - 1];
  if (!el) {
    return { ok: false, message: `No interactive element at index ${targetIndex}.`, total: candidates.length };
  }

  const label = (
    el.innerText ||
    el.getAttribute('aria-label') ||
    el.getAttribute('placeholder') ||
    el.getAttribute('title') ||
    el.getAttribute('name') ||
    el.getAttribute('value') ||
    ''
  ).replace(/\s+/g, ' ').trim().slice(0, 160);

  el.scrollIntoView({ block: 'center', inline: 'center' });
  el.click();
  return { ok: true, tag: el.tagName.toLowerCase(), label, total: candidates.length };
}"""
    result = await page.evaluate(script, [index])
    return result if isinstance(result, dict) else {"ok": False, "message": "Unexpected browser result."}


async def _type_interactive_index(page, index: int, text: str, press_enter: bool) -> dict:
    script = r"""([targetIndex, inputText, pressEnter]) => {
  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.visibility !== 'hidden' &&
      style.display !== 'none';
  };

  const selectors = [
    'input',
    'textarea',
    'select',
    '[contenteditable="true"]',
    '[tabindex]'
  ];

  const candidates = Array.from(document.querySelectorAll(selectors.join(','))).filter(isVisible);
  const el = candidates[targetIndex - 1];
  if (!el) {
    return { ok: false, message: `No typable element at index ${targetIndex}.`, total: candidates.length };
  }

  const label = (
    el.innerText ||
    el.getAttribute('aria-label') ||
    el.getAttribute('placeholder') ||
    el.getAttribute('title') ||
    el.getAttribute('name') ||
    el.getAttribute('value') ||
    ''
  ).replace(/\s+/g, ' ').trim().slice(0, 160);

  el.scrollIntoView({ block: 'center', inline: 'center' });
  el.focus();

  if (el.tagName.toLowerCase() === 'select') {
    return { ok: false, message: 'Target is a select element; use browser_click_index or selector-based action.', label };
  }

  if (el.isContentEditable) {
    el.textContent = inputText;
  } else {
    el.value = inputText;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  if (pressEnter) {
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
  }

  return { ok: true, tag: el.tagName.toLowerCase(), label, total: candidates.length };
}"""
    result = await page.evaluate(script, [index, text, press_enter])
    return result if isinstance(result, dict) else {"ok": False, "message": "Unexpected browser result."}


async def _peek_typable_index(page, index: int) -> dict:
    script = r"""([targetIndex]) => {
  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.visibility !== 'hidden' &&
      style.display !== 'none';
  };

  const selectors = [
    'input',
    'textarea',
    'select',
    '[contenteditable="true"]',
    '[tabindex]'
  ];

  const candidates = Array.from(document.querySelectorAll(selectors.join(','))).filter(isVisible);
  const el = candidates[targetIndex - 1];
  if (!el) {
    return { ok: false, message: `No typable element at index ${targetIndex}.`, total: candidates.length };
  }

  const label = (
    el.innerText ||
    el.getAttribute('aria-label') ||
    el.getAttribute('placeholder') ||
    el.getAttribute('title') ||
    el.getAttribute('name') ||
    el.getAttribute('value') ||
    ''
  ).replace(/\s+/g, ' ').trim().slice(0, 160);

  return {
    ok: true,
    tag: el.tagName.toLowerCase(),
    type: (el.getAttribute('type') || '').slice(0, 60),
    label
  };
}"""
    result = await page.evaluate(script, [index])
    return result if isinstance(result, dict) else {"ok": False, "message": "Unexpected browser result."}


def register(mcp):
    @mcp.tool()
    async def browser_navigate(url: str) -> str:
        """
        Navigate the browser to a specific URL.
        Use this to start a web browsing session.
        """
        global _http_state
        try:
            page = await _get_page()
            await page.goto(url, wait_until="domcontentloaded")
            return await _browser_state_text(page, limit=20)
        except Exception as e:
            if _browser_backend == "http":
                try:
                    state = await _http_navigate(url)
                    return _http_state_text(state, limit=20)
                except Exception as inner:
                    return f"Error navigating browser: {inner}"
            return f"Error navigating browser: {e}"

    @mcp.tool()
    async def browser_open_grid(title: str, urls: list[str]) -> str:
        """
        Visually display a grid of 3-5 concurrent website tabs on screen using an HTML dashboard.
        This provides a "Deep Research" view allowing the user to see all sites at once.
        """
        try:
            if _browser_backend == "http":
                return "HTTP fallback does not support visual grid layout. Use browser_navigate instead."

            if not urls:
                return "No URLs provided for grid."

            page = await _get_page()
            html_content = _grid_dashboard_html(title, urls)
            await page.set_content(html_content, wait_until="domcontentloaded")
            return f"Opened browser grid layout with {len(urls)} concurrent visual tabs."
        except Exception as e:
            if _browser_backend == "http":
                return "HTTP fallback does not support visual grid layout. Use browser_navigate instead."
            return f"Error opening browser grid: {e}"

    @mcp.tool()
    async def browser_get_state(limit: int = 30) -> str:
        """
        Return a browser-use style snapshot of the current page with indexed interactive elements.
        Use this before clicking or typing when selectors are unknown.
        """
        try:
            if _browser_backend == "http":
                if not _http_state:
                    return "No browser page is loaded yet."
                return _http_state_text(_http_state, limit=limit)

            page = await _get_page()
            return await _browser_state_text(page, limit=limit)
        except Exception as e:
            if _browser_backend == "http" and _http_state:
                return _http_state_text(_http_state, limit=limit)
            return f"Error getting browser state: {e}"

    @mcp.tool()
    async def browser_click(selector: str) -> str:
        """
        Click on an element on the current web page using a CSS selector.
        """
        try:
            if _browser_backend == "http":
                return "HTTP fallback does not support CSS-selector clicks. Use browser_click_index or browser_click_text."
            page = await _get_page()
            await page.click(selector, timeout=5000)
            return f"Clicked element matching '{selector}' successfully."
        except Exception as e:
            return f"Error clicking element: {e}"

    @mcp.tool()
    async def browser_click_index(index: int) -> str:
        """
        Click an indexed interactive element from browser_get_state.
        This is often more reliable for agents than hand-writing CSS selectors.
        """
        try:
            if index <= 0:
                return "Index must be greater than zero."

            if _browser_backend == "http":
                if not _http_state:
                    return "No browser page is loaded yet."
                items = _http_state.get("elements", [])
                if index > len(items):
                    return f"No interactive element at index {index}."
                item = items[index - 1]
                href = item.get("href")
                if not href:
                    return (
                        f"HTTP fallback found browser element [{index}] {_http_element_label(item)}, "
                        "but only link navigation is supported in fallback mode."
                    )
                state = await _http_navigate(href)
                return f"Clicked browser element [{index}] {item.get('tag', '?')} :: {_http_element_label(item)}\n\n{_http_state_text(state, limit=20)}"

            page = await _get_page()
            result = await _click_interactive_index(page, index)
            if result.get("ok"):
                label = result.get("label") or "(unlabeled)"
                return f"Clicked browser element [{index}] {result.get('tag', '?')} :: {label}"
            return result.get("message") or f"Could not click browser element [{index}]."
        except Exception as e:
            return f"Error clicking indexed browser element: {e}"

    @mcp.tool()
    async def browser_click_text(text: str, exact: bool = False) -> str:
        """
        Click the first visible link or button that matches the provided text.
        Use this when the element's text is known but its selector is not.
        """
        try:
            if not text.strip():
                return "No text provided."

            if _browser_backend == "http":
                if not _http_state:
                    return "No browser page is loaded yet."
                item = _http_find_element_by_text(_http_state, text, exact)
                if not item:
                    return f"No browser element matched '{text.strip()}'."
                href = item.get("href")
                if not href:
                    return (
                        f"HTTP fallback matched '{_http_element_label(item)}', "
                        "but only link navigation is supported in fallback mode."
                    )
                state = await _http_navigate(href)
                return f"Clicked browser element with text matching '{text.strip()}'.\n\n{_http_state_text(state, limit=20)}"

            page = await _get_page()
            if exact:
                await page.get_by_text(text.strip(), exact=True).first.click(timeout=5000)
            else:
                await page.get_by_text(text.strip(), exact=False).first.click(timeout=5000)
            return f"Clicked browser element with text matching '{text.strip()}'."
        except Exception as e:
            return f"Error clicking browser text: {e}"

    @mcp.tool()
    async def browser_type(selector: str, text: str) -> str:
        """
        Type text into an input field matching the CSS selector.
        """
        try:
            if _browser_backend == "http":
                return "HTTP fallback does not support CSS-selector typing."
            page = await _get_page()
            await page.fill(selector, text, timeout=5000)
            return f"Typed text into '{selector}' successfully."
        except Exception as e:
            return f"Error typing text: {e}"

    @mcp.tool()
    async def browser_type_index(index: int, text: str, press_enter: bool = False) -> str:
        """
        Type text into an indexed typable element from browser_get_state.
        Use this when the target input is visible but selector-writing is brittle.
        """
        try:
            if index <= 0:
                return "Index must be greater than zero."

            if _browser_backend == "http":
                return "HTTP fallback does not support form typing yet. Use Playwright mode for live form interaction."

            page = await _get_page()
            preview = await _peek_typable_index(page, index)
            if not preview.get("ok"):
                return preview.get("message") or f"Could not inspect browser element [{index}]."

            decision, approval_request = authorize_tool_call(
                "browser_type_index",
                {
                    "index": index,
                    "text": text,
                    "press_enter": press_enter,
                    "current_url": page.url,
                    "element_label": preview.get("label") or f"indexed element [{index}]",
                },
            )
            if decision.decision != "allow":
                return format_permission_response(decision, approval_request=approval_request)

            result = await _type_interactive_index(page, index, text, press_enter)
            if result.get("ok"):
                label = result.get("label") or "(unlabeled)"
                tail = " and pressed Enter." if press_enter else "."
                record_tool_result(
                    "browser_type_index",
                    decision,
                    result="succeeded",
                    domain=decision.domain,
                    metadata={
                        **decision.metadata,
                        "index": index,
                        "press_enter": press_enter,
                    },
                )
                return f"Typed into browser element [{index}] {result.get('tag', '?')} :: {label}{tail}"
            record_tool_result(
                "browser_type_index",
                decision,
                result="failed",
                domain=decision.domain,
                metadata={
                    **decision.metadata,
                    "index": index,
                    "press_enter": press_enter,
                },
            )
            return result.get("message") or f"Could not type into browser element [{index}]."
        except Exception as e:
            if "decision" in locals():
                record_tool_result(
                    "browser_type_index",
                    decision,
                    result=f"error:{e.__class__.__name__}",
                    domain=decision.domain,
                    metadata={
                        **decision.metadata,
                        "index": index,
                        "press_enter": press_enter,
                    },
                )
            return f"Error typing into indexed browser element: {e}"

    @mcp.tool()
    async def browser_wait_for_text(text: str, timeout_ms: int = 8000) -> str:
        """
        Wait for visible text to appear on the page.
        Useful after navigation, form submission, or other page transitions.
        """
        try:
            if not text.strip():
                return "No text provided."

            if _browser_backend == "http":
                deadline = asyncio.get_running_loop().time() + max(timeout_ms, 1) / 1000
                needle = text.strip().lower()
                while True:
                    if _http_state and needle in (_http_state.get("text", "").lower()):
                        return f"Detected page text matching '{text.strip()}'."
                    if asyncio.get_running_loop().time() >= deadline:
                        return f"Timed out waiting for browser text '{text.strip()}'."
                    await asyncio.sleep(0.5)
                    try:
                        await _http_refresh()
                    except Exception:
                        pass

            page = await _get_page()
            await page.get_by_text(text.strip(), exact=False).first.wait_for(timeout=timeout_ms)
            return f"Detected page text matching '{text.strip()}'."
        except Exception as e:
            return f"Error waiting for browser text: {e}"

    @mcp.tool()
    async def browser_press_key(key: str) -> str:
        """
        Press a keyboard key inside the active browser page.
        Example values: Enter, Tab, ArrowDown, Escape.
        """
        try:
            if not key.strip():
                return "No key provided."
            if _browser_backend == "http":
                return "HTTP fallback does not support keyboard input."
            page = await _get_page()
            normalized_key = key.strip()
            decision, approval_request = authorize_tool_call(
                "browser_press_key",
                {"key": normalized_key, "current_url": page.url},
            )
            if decision.decision != "allow":
                return format_permission_response(decision, approval_request=approval_request)

            await page.keyboard.press(normalized_key)
            record_tool_result(
                "browser_press_key",
                decision,
                result="succeeded",
                domain=decision.domain,
                metadata={**decision.metadata, "key": normalized_key},
            )
            return f"Pressed browser key '{normalized_key}'."
        except Exception as e:
            if "decision" in locals():
                record_tool_result(
                    "browser_press_key",
                    decision,
                    result=f"error:{e.__class__.__name__}",
                    domain=decision.domain,
                    metadata={**decision.metadata, "key": key.strip()},
                )
            return f"Error pressing browser key: {e}"

    @mcp.tool()
    async def browser_dynamic_loop(goal: str, max_steps: int = 6) -> str:
        """
        Run a generic observe-act-verify browser loop using DOM/accessibility-style
        element maps. This is intentionally site-agnostic: it chooses elements by
        role, label, placeholder, href, and visible text rather than hardcoded
        website selectors.
        """
        try:
            from friday.browser.operator import BrowserAction, BrowserOperator, build_element_map_from_records, infer_site_url, wants_first_result_click

            operator = BrowserOperator()
            history: list[dict[str, object]] = []
            lines: list[str] = []

            async def observe_current():
                if _browser_backend == "http":
                    if not _http_state:
                        return build_element_map_from_records([], title="", url="", visible_text="")
                    return build_element_map_from_records(
                        list(_http_state.get("elements", [])),
                        title=str(_http_state.get("title", "")),
                        url=str(_http_state.get("url", "")),
                        visible_text=str(_http_state.get("text", "")),
                    )
                page = await _get_page()
                elements = await _get_interactive_elements(page)
                return build_element_map_from_records(
                    elements,
                    title=await page.title(),
                    url=page.url,
                    visible_text=await page.locator("body").inner_text(timeout=3000),
                )

            async def execute_action(action: BrowserAction) -> str:
                if action.type == "complete":
                    return action.reason or "Goal complete."
                if action.type in {"needs_clarification", "confirm_target"}:
                    return action.reason or "Target is ambiguous; clarification is required."
                if action.type == "navigate":
                    if _browser_backend == "http":
                        state = await _http_navigate(action.url)
                        return f"Navigated to {state.get('url', action.url)}"
                    page = await _get_page()
                    await page.goto(action.url, wait_until="domcontentloaded")
                    return f"Navigated to {page.url}"
                if action.type == "type_into_element":
                    index = int(action.element_id.rsplit(":", 1)[-1])
                    if _browser_backend == "http":
                        return "HTTP fallback can observe pages but cannot type into forms."
                    page = await _get_page()
                    result = await _type_interactive_index(page, index, action.text, bool(action.key))
                    if action.key:
                        await page.keyboard.press(action.key)
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=5000)
                        except Exception:
                            pass
                    return result.get("message") or f"Typed into element {action.element_id}."
                if action.type == "click_element":
                    index = int(action.element_id.rsplit(":", 1)[-1])
                    if _browser_backend == "http":
                        if not _http_state:
                            return "No HTTP page state is available."
                        items = list(_http_state.get("elements", []))
                        if index <= 0 or index > len(items):
                            return f"No element at index {index}."
                        href = items[index - 1].get("href")
                        if not href:
                            return "HTTP fallback can only click links with href targets."
                        state = await _http_navigate(str(href))
                        return f"Clicked link and navigated to {state.get('url', href)}"
                    page = await _get_page()
                    result = await _click_interactive_index(page, index)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    return result.get("message") or f"Clicked element {action.element_id}."
                if action.type == "screenshot_fallback":
                    if _browser_backend == "http":
                        return "Screenshot fallback requires Playwright mode."
                    page = await _get_page()
                    target = Path(os.environ.get("FRIDAY_WORKSPACE_DIR", str(Path.cwd() / "workspace"))) / "screenshots" / "browser_dynamic_fallback.png"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(path=str(target), full_page=True)
                    return f"Saved browser screenshot fallback: {target}"
                return f"Unsupported dynamic browser action: {action.type}"

            if not _page and _browser_backend != "http":
                target_url = infer_site_url(goal)
                if target_url:
                    page = await _get_page()
                    await page.goto(target_url, wait_until="domcontentloaded")
                    lines.append(f"Navigated to {target_url}")
            elif _browser_backend == "http" and not _http_state:
                target_url = infer_site_url(goal)
                if target_url:
                    state = await _http_navigate(target_url)
                    lines.append(f"Navigated to {state.get('url', target_url)}")

            for step in range(1, max(1, max_steps) + 1):
                observation = await observe_current()
                action = operator.decide_next_action(goal, observation, history)
                history.append(action.to_dict())
                decision = operator.permission_for_action(action, observation)
                lines.append(f"Step {step}: selected {action.type} ({action.reason})")
                if action.type in {"needs_clarification", "confirm_target"}:
                    lines.append(action.reason or "Target is ambiguous; clarification is required.")
                    break
                if decision.get("decision") != "allow":
                    lines.append(f"Permission {decision.get('decision')}: {decision.get('reason')}")
                    break
                result = await execute_action(action)
                lines.append(f"Result: {result}")
                if action.type in {"complete", "screenshot_fallback"}:
                    break
                if "search" in goal.lower() and action.type == "type_into_element" and not wants_first_result_click(goal):
                    break

            return "\n".join(lines) if lines else "No dynamic browser action was selected."
        except Exception as e:
            return f"Error in dynamic browser loop: {e}"

    @mcp.tool()
    async def browser_scroll(direction: str = "down", amount: int = 800) -> str:
        """
        Scroll the active page up or down by a pixel amount.
        """
        try:
            if _browser_backend == "http":
                return "HTTP fallback does not support scrolling. Use browser_read_page to inspect the fetched content."
            page = await _get_page()
            delta = abs(amount)
            if direction.strip().lower() == "up":
                delta = -delta
            await page.mouse.wheel(0, delta)
            return f"Scrolled browser page {direction.strip().lower() or 'down'} by {abs(amount)} pixels."
        except Exception as e:
            return f"Error scrolling browser page: {e}"

    @mcp.tool()
    async def browser_read_page() -> str:
        """
        Read the visible structure of the current page to understand what is shown and what to do next.
        """
        try:
            if _browser_backend == "http":
                if not _http_state:
                    return "No browser page is loaded yet."
                summary = _http_state_text(_http_state, limit=25)
                content = _http_state.get("content") or _http_state.get("text") or ""
                return f"{summary}\n\nPage Content (HTTP Fallback):\n{content[:4000]}"

            page = await _get_page()
            summary = await _browser_state_text(page, limit=25)
            content = await page.evaluate(
                """() => {
                let items = [];
                document.querySelectorAll('a, button, input, h1, h2, h3, p, li').forEach(el => {
                    let rect = el.getBoundingClientRect();
                    const text = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').trim();
                    if (rect.width > 0 && rect.height > 0 && text) {
                        items.push(`${el.tagName} | ${text.substring(0, 100)}`);
                    }
                });
                return items.join('\\n');
            }"""
            )
            return f"{summary}\n\nPage Content (Visual Tags):\n{content[:4000]}"
        except Exception as e:
            return f"Error reading page: {e}"

    @mcp.tool()
    async def browser_close() -> str:
        """
        Close the active browser session.
        """
        global _playwright, _browser, _page, _browser_backend, _http_client, _http_state, _http_backend_reason
        try:
            if _browser:
                await _browser.close()
            if _playwright:
                await _playwright.stop()
            if _http_client:
                await _http_client.aclose()
            _playwright, _browser, _page = None, None, None
            _http_client, _http_state = None, None
            _browser_backend = "playwright"
            _http_backend_reason = ""
            return "Browser session closed successfully."
        except Exception as e:
            return f"Error closing browser: {e}"
