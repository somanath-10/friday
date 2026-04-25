"""
SOTA Web Research Tool — uses Firecrawl for deep LLM-ready scraping
and Trafilatura as a robust, open-source fallback.
"""
import os
import httpx

try:
    import trafilatura
except ImportError:
    trafilatura = None

async def deep_scrape_url(url: str, use_firecrawl: bool = True) -> str:
    """
    Deeply scrape a URL and return clean, LLM-ready Markdown.
    Uses Firecrawl (if API key present) for full-page JS rendering
    or Trafilatura for fast, reliable extraction of content.
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY")

    if use_firecrawl and api_key:
        try:
            # Use Firecrawl API directly via httpx for maximum control
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"url": url, "formats": ["markdown"]}

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post("https://api.firecrawl.dev/v1/scrape", json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("data", {}).get("markdown", "No markdown found in response.")
        except Exception:
            # Fallback to trafilatura on error
            pass

    # Fallback to Trafilatura when available
    if trafilatura is None:
        return (
            "Scraping fallback is unavailable because 'trafilatura' is not installed. "
            "Run 'uv sync' to install optional tool dependencies."
        )

    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            result = trafilatura.extract(downloaded, output_format='markdown', include_links=True)
            if result:
                return f"[Trafilatura Fallback Scrape]\n\n{result}"
        return "Failed to extract content from the URL."
    except Exception as e:
        return f"Scraping error: {str(e)}"

def register(mcp):
    mcp.tool()(deep_scrape_url)
