"""
Browser automation tools for FRIDAY.

This module keeps a persistent Playwright browser session and exposes both
selector-based and index-based actions so the agent can inspect a page, choose
an element, and act without brittle CSS-only workflows.
"""

from __future__ import annotations

import os

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

_playwright = None
_browser = None
_page = None


def _require_playwright() -> None:
    if async_playwright is None:
        raise RuntimeError(
            "Playwright is not installed. Run `uv sync` and `playwright install chromium` before using browser tools."
        )


def _browser_headless() -> bool:
    value = os.environ.get("FRIDAY_BROWSER_HEADLESS", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


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


async def _get_page():
    global _playwright, _browser, _page
    _require_playwright()
    if not _page:
        if not _playwright:
            _playwright = await async_playwright().start()
        if not _browser:
            from pathlib import Path

            downloads_dir = os.environ.get("FRIDAY_DOWNLOADS_DIR", str(Path.home() / "Downloads"))
            _browser = await _playwright.chromium.launch(
                headless=_browser_headless(),
                downloads_path=downloads_dir,
            )
        _page = await _browser.new_page(accept_downloads=True)
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


def register(mcp):
    @mcp.tool()
    async def browser_navigate(url: str) -> str:
        """
        Navigate the browser to a specific URL.
        Use this to start a web browsing session.
        """
        try:
            page = await _get_page()
            await page.goto(url, wait_until="domcontentloaded")
            return await _browser_state_text(page, limit=20)
        except Exception as e:
            return f"Error navigating browser: {e}"

    @mcp.tool()
    async def browser_get_state(limit: int = 30) -> str:
        """
        Return a browser-use style snapshot of the current page with indexed interactive elements.
        Use this before clicking or typing when selectors are unknown.
        """
        try:
            page = await _get_page()
            return await _browser_state_text(page, limit=limit)
        except Exception as e:
            return f"Error getting browser state: {e}"

    @mcp.tool()
    async def browser_click(selector: str) -> str:
        """
        Click on an element on the current web page using a CSS selector.
        """
        try:
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
            page = await _get_page()
            result = await _type_interactive_index(page, index, text, press_enter)
            if result.get("ok"):
                label = result.get("label") or "(unlabeled)"
                tail = " and pressed Enter." if press_enter else "."
                return f"Typed into browser element [{index}] {result.get('tag', '?')} :: {label}{tail}"
            return result.get("message") or f"Could not type into browser element [{index}]."
        except Exception as e:
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
            page = await _get_page()
            await page.keyboard.press(key.strip())
            return f"Pressed browser key '{key.strip()}'."
        except Exception as e:
            return f"Error pressing browser key: {e}"

    @mcp.tool()
    async def browser_scroll(direction: str = "down", amount: int = 800) -> str:
        """
        Scroll the active page up or down by a pixel amount.
        """
        try:
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
        global _playwright, _browser, _page
        try:
            if _browser:
                await _browser.close()
            if _playwright:
                await _playwright.stop()
            _playwright, _browser, _page = None, None, None
            return "Browser session closed successfully."
        except Exception as e:
            return f"Error closing browser: {e}"
