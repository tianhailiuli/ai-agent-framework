"""Web search tool using Sogou (accessible in China, no API key)."""

import re

import requests

from .base import Tool


class WebSearchTool(Tool):
    """Tool for searching the web via Sogou."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the internet for real-time information, news, facts, and any topic. "
            'Input: {"query": "search keywords"}. '
            "Returns top search results with title, snippet and URL."
        )

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Search the internet for real-time information, news, facts, and any topic. Returns top search results with title, snippet and URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query, e.g. '2024年奥运会金牌榜', 'Python最新版本特性', '今天的新闻'"
                        }
                    },
                    "required": ["query"]
                }
            }
        }

    def run(self, params: dict) -> dict:
        query = params.get("query", "")
        if not query:
            return {
                "status": "error",
                "result": None,
                "message": "No search query provided.",
            }

        try:
            results = self._search_sogou(query)
            if not results:
                return {
                    "status": "success",
                    "result": [],
                    "message": f"No results found for '{query}'.",
                }
            return {
                "status": "success",
                "result": results,
                "message": f"Found {len(results)} web results for '{query}'.",
            }
        except Exception as e:
            return {
                "status": "error",
                "result": None,
                "message": f"Web search error: {str(e)}",
            }

    def _search_sogou(self, query: str) -> list[dict]:
        """Search Sogou and parse results from HTML."""
        url = "https://www.sogou.com/web"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        params = {"query": query}

        resp = requests.get(url, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
        html = resp.text

        results = []

        # Split by vrwrap blocks
        parts = html.split('class="vrwrap"')
        # Skip first part (before first vrwrap)
        for part in parts[1:15]:
            # Extract title from h3.vr-title > a
            title_match = re.search(
                r'<h3[^>]*class="vr-title"[^>]*>.*?<a[^>]*>(.*?)</a>.*?</h3>',
                part,
                re.DOTALL,
            )

            # Extract URL from href
            url_match = re.search(
                r'href="(/link\?url=[^"]+)"',
                part,
            )

            # Extract snippet: look for text after </h3> until </div> (end of vrwrap block)
            snippet = ""
            after_h3 = part.split('</h3>')[-1] if '</h3>' in part else part
            # Remove script/style tags
            after_h3 = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', after_h3, flags=re.DOTALL)
            # Extract plain text
            text_only = re.sub(r'<[^>]+>', ' ', after_h3)
            text_only = ' '.join(text_only.split())
            if len(text_only) > 10:
                snippet = text_only

            title = self._clean_html(title_match.group(1) if title_match else "")
            result_url = url_match.group(1) if url_match else ""

            if result_url.startswith("/"):
                result_url = "https://www.sogou.com" + result_url

            if title:
                results.append({
                    "title": title,
                    "snippet": snippet,
                    "url": result_url,
                })

        return results

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags and decode entities."""
        if not text:
            return ""
        # Remove tags
        text = re.sub(r'<[^>]+>', '', text)
        # Remove Sogou highlight markers
        text = text.replace('<!--red_beg-->', '')
        text = text.replace('<!--red_end-->', '')
        # Decode common entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&#39;', "'")
        text = text.replace('&#0183;', '·')
        text = text.replace('\n', ' ')
        text = text.replace('\r', ' ')
        text = ' '.join(text.split())
        return text.strip()
