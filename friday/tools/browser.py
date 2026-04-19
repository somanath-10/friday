"""
Browser Automation tool — allows F.R.I.D.A.Y to operate a headless browser, navigate, click, fill forms, and read screen content.
"""

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


async def _get_page():
    global _playwright, _browser, _page
    _require_playwright()
    if not _page:
        if not _playwright:
            _playwright = await async_playwright().start()
        if not _browser:
            from pathlib import Path
            import os
            downloads_dir = os.environ.get("FRIDAY_DOWNLOADS_DIR", str(Path.home() / "Downloads"))
            _browser = await _playwright.chromium.launch(headless=False, downloads_path=downloads_dir)
        _page = await _browser.new_page(accept_downloads=True)
    return _page

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
            return f"Navigated to {url}. Page title: {await page.title()}"
        except Exception as e:
            return f"Error navigating browser: {e}"

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
    async def browser_read_page() -> str:
        """
        Read the textual representation of the current page to figure out what to click next or what information is presented.
        """
        try:
            page = await _get_page()
            # Extract basic structure
            content = await page.evaluate('''() => {
                let items = [];
                document.querySelectorAll('a, button, input, h1, h2, h3, p').forEach(el => {
                    let rect = el.getBoundingClientRect();
                    if(rect.width > 0 && rect.height > 0 && el.innerText) {
                        items.push(`${el.tagName} | ${el.innerText.trim().substring(0, 100)}`);
                    }
                });
                return items.join('\\n');
            }''')
            return f"Page Content (Visual Tags):\n{content[:4000]}\nUse elements to formulate CSS selectors."
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
