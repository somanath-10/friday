"""
Web tools — search, fetch pages, and global news briefings.
"""

import html
import httpx
import xml.etree.ElementTree as ET
import asyncio
import re
import os
import urllib.parse

SEED_FEEDS = [
    'https://feeds.bbci.co.uk/news/world/rss.xml',
    'https://www.cnbc.com/id/100727362/device/rss/rss.html',
    'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
    'https://www.aljazeera.com/xml/rss/all.xml'
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


async def fetch_and_parse_feed(client, url):
    """Helper function to handle a single feed request and parse its XML."""
    try:
        response = await client.get(url, headers={'User-Agent': 'Friday-AI/1.0'}, timeout=5.0)
        if response.status_code != 200:
            return []

        root = ET.fromstring(response.content)
        source_name = url.split('.')[1].upper()

        feed_items = []
        items = root.findall(".//item")[:5]
        for item in items:
            title = item.findtext("title")
            description = item.findtext("description")
            link = item.findtext("link")

            if title:
                title = html.unescape(title).strip()
            if description:
                description = html.unescape(re.sub('<[^<]+?>', '', description)).strip()

            feed_items.append({
                "source": source_name,
                "title": title,
                "summary": description[:200] + "..." if description else "",
                "link": link
            })
        return feed_items
    except Exception:
        return []


async def _brave_search(client: httpx.AsyncClient, query: str, count: int = 5) -> list:
    """Use Brave Search API if key is available."""
    brave_key = os.environ.get("BRAVE_API_KEY", "")
    if not brave_key:
        return []
    try:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": count, "text_decorations": False},
            headers={"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": brave_key},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for item in data.get("web", {}).get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                })
            return results
    except Exception:
        pass
    return []


async def _ddg_html_search(client: httpx.AsyncClient, query: str) -> list:
    """Scrape DuckDuckGo HTML search results (no API key needed)."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        resp = await client.get(url, headers=HEADERS, timeout=10)
        if resp.status_code >= 400:
            return []

        html = resp.text
        results = []

        # Extract result blocks
        blocks = re.findall(
            r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )

        for url_raw, title_html, snippet_html in blocks[:8]:
            title = html.unescape(re.sub('<[^>]+>', '', title_html)).strip()
            snippet = html.unescape(re.sub('<[^>]+>', '', snippet_html)).strip()
            # DDG uses redirect URLs — extract real URL
            real_url = url_raw
            uddg_match = re.search(r'uddg=([^&]+)', url_raw)
            if uddg_match:
                real_url = urllib.parse.unquote(uddg_match.group(1))
            if title and snippet:
                results.append({"title": title, "url": real_url, "snippet": snippet})

        return results
    except Exception:
        return []


async def _ddg_instant_answer(client: httpx.AsyncClient, query: str) -> str:
    """DuckDuckGo instant answer as last-resort fallback."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
        resp = await client.get(url, timeout=8)
        if resp.status_code < 400:
            data = resp.json()
            parts = []
            for key in ("Answer", "Definition", "Abstract", "AbstractText"):
                val = html.unescape(data.get(key, "").strip())
                if val:
                    parts.append(val)
            for t in data.get("RelatedTopics", [])[:3]:
                if isinstance(t, dict) and "Text" in t:
                    parts.append(html.unescape(t["Text"]))
            if parts:
                return " ".join(parts)[:600]
    except Exception:
        pass
    return ""


def register(mcp):

    @mcp.tool()
    async def get_world_news() -> str:
        """
        Fetches the latest global headlines from major news outlets simultaneously.
        Use this when the user asks 'What's going on in the world?' or for recent events.
        """
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            tasks = [fetch_and_parse_feed(client, url) for url in SEED_FEEDS]
            results_of_lists = await asyncio.gather(*tasks)
            all_articles = [item for sublist in results_of_lists for item in sublist]

        if not all_articles:
            return "The global news grid is unresponsive, sir. I'm unable to pull headlines."

        report = ["### GLOBAL NEWS BRIEFING (LIVE)\n"]
        for entry in all_articles[:12]:
            report.append(f"**[{entry['source']}]** {entry['title']}")
            report.append(f"{entry['summary']}")
            report.append(f"Link: {entry['link']}\n")

        return "\n".join(report)

    @mcp.tool()
    async def search_web(query: str) -> str:
        """
        Search the web for any query and return a summary of real search results.
        Use this for any question requiring current information, facts, news, or research.
        Tries Brave Search API first (if BRAVE_API_KEY is set), then falls back to DuckDuckGo scraping.
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=12) as client:
                # Priority 1: Brave API (best results)
                results = await _brave_search(client, query)

                # Priority 2: DDG HTML scraping
                if not results:
                    results = await _ddg_html_search(client, query)

                if results:
                    parts = [f"Search results for: '{query}'\n"]
                    for i, r in enumerate(results[:6], 1):
                        parts.append(f"{i}. **{r['title']}**")
                        if r.get("snippet"):
                            parts.append(f"   {r['snippet']}")
                        parts.append(f"   {r['url']}")
                    return "\n".join(parts)

                # Priority 3: DDG instant answer
                instant = await _ddg_instant_answer(client, query)
                if instant:
                    return f"Search result for '{query}':\n{instant}"

                return f"Search yielded no clear results for '{query}'. Try rephrasing or use fetch_url with a specific URL."

        except Exception as e:
            return f"Search error: {str(e)}"

    @mcp.tool()
    async def search_code(query: str) -> str:
        """
        Search for programming-related code snippets, documentation, and technical resources.
        Searches Stack Overflow, GitHub, and official docs. Use for coding questions.
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=12) as client:
                tech_query = f"{query} site:stackoverflow.com OR site:github.com OR site:docs.python.org"

                results = await _brave_search(client, tech_query)
                if not results:
                    results = await _ddg_html_search(client, tech_query)

                if results:
                    parts = [f"Code/Tech search: '{query}'\n"]
                    for i, r in enumerate(results[:5], 1):
                        parts.append(f"{i}. **{r['title']}**")
                        if r.get("snippet"):
                            parts.append(f"   {r['snippet']}")
                        parts.append(f"   {r['url']}")
                    return "\n".join(parts)

                instant = await _ddg_instant_answer(client, query)
                if instant:
                    return f"Tech result for '{query}':\n{instant}"

                return f"No code resources found for '{query}'. Try searching directly on stackoverflow.com or github.com."

        except Exception as e:
            return f"Code search error: {str(e)}"

    @mcp.tool()
    async def fetch_url(url: str) -> str:
        """
        Fetch the text content of any URL. Use to read articles, documentation, or web pages.
        Returns the first 4000 characters of the page content.
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                response = await client.get(url, headers=HEADERS)
                response.raise_for_status()

                content = response.text
                # Strip common HTML tags for readability
                content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
                content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL)
                content = re.sub(r'<[^>]+>', ' ', content)
                content = re.sub(r'\s+', ' ', content).strip()

                return content[:5000] + ("\n\n... [content truncated] ..." if len(content) > 5000 else "")
        except Exception as e:
            return f"Error fetching URL: {str(e)}"

    @mcp.tool()
    async def open_world_monitor() -> str:
        """
        Opens the World Monitor dashboard (worldmonitor.app) in the system's web browser.
        Use this when the user wants a visual overview of global events or a real-time map.
        """
        import webbrowser
        url = "https://worldmonitor.app/"
        try:
            webbrowser.open(url)
            return "Displaying the World Monitor on your primary screen now, sir."
        except Exception as e:
            return f"I'm unable to initialize the visual monitor: {str(e)}"

    @mcp.tool()
    async def open_url(url: str) -> str:
        """
        Open any URL in the default web browser on the host machine.
        Use this when the user says 'open this link', 'go to this website', 'show me X website'.
        """
        import webbrowser
        try:
            webbrowser.open(url)
            return f"Opened {url} in your browser."
        except Exception as e:
            return f"Error opening URL: {str(e)}"
