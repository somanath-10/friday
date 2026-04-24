"""
Deep Research module for FRIDAY.
Provides capability to analyze multiple web pages simultaneously and display them in a visual grid on screen.
"""

from __future__ import annotations

import asyncio
import httpx

from . import browser

def register(mcp):
    
    async def _fetch_and_parse(client: httpx.AsyncClient, url: str) -> str:
        try:
            response = await client.get(url, follow_redirects=True, timeout=20.0)
            response.raise_for_status()

            parser = browser._HTMLSnapshotParser(str(response.url))
            parser.feed(response.text)
            snapshot = parser.snapshot()

            title = snapshot["title"] or url
            text_content = snapshot["text"][:8000]

            return f"--- SOURCE: {title} ({url}) ---\n{text_content}\n"
        except Exception as e:
            return f"--- SOURCE (FAILED): {url} ---\nError: {e}\n"

    @mcp.tool()
    async def deep_research_grid(topic: str, urls: list[str]) -> str:
        """
        Start a Deep Research session. 
        It visually opens a 3-5 window grid on screen containing the chosen URLs, 
        and simultaneously reads/scrapes all of them in the background, returning their text.
        
        Use this when the user asks for "deep research" or to summarize multiple websites at once.
        Provide a short topic label, and a list of 3-5 specific URLs you identified as useful.
        """
        if not urls:
            return "No URLs provided for deep research."

        # 1. Visually layout the grid for the user using Playwright if available
        grid_status = ""
        try:
            if browser._browser_backend != "http":
                page = await browser._get_page()
                html_content = browser._grid_dashboard_html(topic, urls)
                await page.set_content(html_content, wait_until="domcontentloaded")
                grid_status = f"Successfully opened visual grid with {len(urls)} concurrent windows."
            else:
                grid_status = "Skipped visual grid due to HTTP fallback backend."
        except Exception as e:
            if browser._browser_backend == "http":
                grid_status = "Skipped visual grid due to HTTP fallback backend."
            else:
                grid_status = f"Could not open visual grid: {e}"

        # 2. Concurrently scrape the pages
        results = []
        async with httpx.AsyncClient(headers=browser.HEADERS) as client:
            tasks = [_fetch_and_parse(client, url) for url in urls]
            results = await asyncio.gather(*tasks)

        merged_data = "\n\n".join(results)

        return (
            f"{grid_status}\n\n"
            f"Here is the raw text content gathered from the {len(urls)} sources. "
            f"Synthesize this information into a thorough research report for the user:\n\n"
            f"{merged_data}"
        )
