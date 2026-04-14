"""
Web tools — search, fetch pages, and global news briefings.
"""

import httpx
import xml.etree.ElementTree as ET
import asyncio  # Required for parallel execution
import re
import json
from datetime import datetime

SEED_FEEDS = [
    'https://feeds.bbci.co.uk/news/world/rss.xml',
    'https://www.cnbc.com/id/100727362/device/rss/rss.html',
    'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
    'https://www.aljazeera.com/xml/rss/all.xml'
]

# Programming-focused search sites
PROGRAMMING_SITES = [
    'stackoverflow.com',
    'github.com',
    'docs.python.org',
    'developer.mozilla.org',
    'dev.to',
    'medium.com/tag/programming'
]

async def fetch_and_parse_feed(client, url):
    """Helper function to handle a single feed request and parse its XML."""
    try:
        response = await client.get(url, headers={'User-Agent': 'Friday-AI/1.0'}, timeout=5.0)
        if response.status_code != 200:
            return []

        root = ET.fromstring(response.content)
        # Extract source name from URL (e.g., 'BBC' or 'NYTIMES')
        source_name = url.split('.')[1].upper()
        
        feed_items = []
        # Get top 5 items per feed
        items = root.findall(".//item")[:5]
        for item in items:
            title = item.findtext("title")
            description = item.findtext("description")
            link = item.findtext("link")
            
            if description:
                description = re.sub('<[^<]+?>', '', description).strip()

            feed_items.append({
                "source": source_name,
                "title": title,
                "summary": description[:200] + "..." if description else "",
                "link": link
            })
        return feed_items
    except Exception:
        # If one feed fails, return an empty list so others can still succeed
        return []

def register(mcp):

    @mcp.tool()
    async def get_world_news() -> str:
        """
        Fetches the latest global headlines from major news outlets simultaneously.
        Use this when the user asks 'What's going on in the world?' or for recent events.
        """
        
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            # 1. Create a list of 'tasks' (one for each URL)
            tasks = [fetch_and_parse_feed(client, url) for url in SEED_FEEDS]
            
            # 2. Fire them all at once and wait for the results
            # results will be a list of lists: [[news from bbc], [news from nyt], ...]
            results_of_lists = await asyncio.gather(*tasks)
            
            # 3. Flatten the list of lists into a single list of articles
            all_articles = [item for sublist in results_of_lists for item in sublist]

        if not all_articles:
            return "The global news grid is unresponsive, sir. I'm unable to pull headlines."

        # 4. Format the final briefing
        report = ["### GLOBAL NEWS BRIEFING (LIVE)\n"]
        # Limit to top 12 items so the AI doesn't get overwhelmed
        for entry in all_articles[:12]:
            report.append(f"**[{entry['source']}]** {entry['title']}")
            report.append(f"{entry['summary']}")
            report.append(f"Link: {entry['link']}\n")

        return "\n".join(report)

    @mcp.tool()
    async def search_web(query: str) -> str:
        """Search the web for a given query and return a summary of results."""
        # For now, we'll use DuckDuckGo instant answer API as a free alternative
        # In production, you might want to use Google Custom Search or another service
        try:
            import urllib.parse
            encoded_query = urllib.parse.quote_plus(query)
            url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_html=1&skip_disambig=1"

            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()

                    # Extract relevant information
                    abstract = data.get('Abstract', '')
                    abstract_text = data.get('AbstractText', '')
                    related_topics = data.get('RelatedTopics', [])
                    definition = data.get('Definition', '')
                    answer = data.get('Answer', '')

                    result_parts = []
                    if answer:
                        result_parts.append(answer)
                    if definition:
                        result_parts.append(definition)
                    if abstract:
                        result_parts.append(abstract)
                    elif abstract_text:
                        result_parts.append(abstract_text)

                    # Add some related topics if available
                    if related_topics and len(result_parts) < 3:
                        for topic in related_topics[:3]:  # Limit to 3 topics
                            if isinstance(topic, dict) and 'Text' in topic:
                                result_parts.append(topic['Text'])
                            elif isinstance(topic, str):
                                result_parts.append(topic)

                    if result_parts:
                        return " ".join(result_parts)[:800]  # Limit response length
                    else:
                        return f"I searched for '{query}' but didn't find a clear answer. You might want to try more specific terms or check your spelling."
                else:
                    return f"Search service temporarily unavailable. Status: {response.status_code}"
        except Exception as e:
            return f"I encountered an error while searching: {str(e)}"

    @mcp.tool()
    async def search_code(query: str) -> str:
        """Search for programming-related code snippets and documentation."""
        try:
            import urllib.parse
            # Add site restrictions for programming resources
            programming_query = f"{query} site:stackoverflow.com OR site:github.com OR site:docs.python.org OR site:developer.mozilla.org"
            encoded_query = urllib.parse.quote_plus(programming_query)
            url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_html=1&skip_disambig=1"

            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()

                    # Extract relevant information
                    abstract = data.get('Abstract', '')
                    abstract_text = data.get('AbstractText', '')
                    related_topics = data.get('RelatedTopics', [])
                    definition = data.get('Definition', '')
                    answer = data.get('Answer', '')

                    result_parts = []
                    if answer:
                        result_parts.append(answer)
                    if definition:
                        result_parts.append(definition)
                    if abstract:
                        result_parts.append(abstract)
                    elif abstract_text:
                        result_parts.append(abstract_text)

                    # Add some related topics if available
                    if related_topics and len(result_parts) < 3:
                        for topic in related_topics[:3]:  # Limit to 3 topics
                            if isinstance(topic, dict) and 'Text' in topic:
                                result_parts.append(topic['Text'])
                            elif isinstance(topic, str):
                                result_parts.append(topic)

                    if result_parts:
                        return " ".join(result_parts)[:800]  # Limit response length
                    else:
                        return f"I searched for programming resources on '{query}' but didn't find a clear answer. You might want to try more specific terms or check GitHub/Stack Overflow directly."
                else:
                    return f"Code search service temporarily unavailable. Status: {response.status_code}"
        except Exception as e:
            return f"I encountered an error while searching for code: {str(e)}"

    @mcp.tool()
    async def fetch_url(url: str) -> str:
        """Fetch the raw text content of a URL."""
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text[:4000]
    
    @mcp.tool()
    async def open_world_monitor() -> str:
        """
        Opens the World Monitor dashboard (worldmonitor.app) in the system's web browser.
        Use this when the user wants a visual overview of global events or a real-time map.
        """
        import webbrowser
        url = "https://worldmonitor.app/"
        
        try:
            # This opens the URL in the default browser (Chrome/Edge/Safari)
            webbrowser.open(url)
            return "Displaying the World Monitor on your primary screen now, sir."
        except Exception as e:
            return f"I'm unable to initialize the visual monitor: {str(e)}"