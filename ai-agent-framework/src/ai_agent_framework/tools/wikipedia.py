"""Wikipedia search tool."""

import requests
import urllib.parse

from .base import Tool


class WikipediaTool(Tool):
    """Tool for searching Wikipedia articles."""

    @property
    def name(self) -> str:
        return "wikipedia_search"

    @property
    def description(self) -> str:
        return (
            "Search Wikipedia for article summaries. "
            'Input: {"query": "search term", "lang": "zh" (optional, default zh)}. '
            "Returns summaries of top matching articles."
        )

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Search Wikipedia for article summaries. Returns top 3 matching articles with title, summary and URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search term or topic to look up on Wikipedia"
                        },
                        "lang": {
                            "type": "string",
                            "description": "Language code like 'zh' or 'en'. Default is 'zh'."
                        }
                    },
                    "required": ["query"]
                }
            }
        }

    def run(self, params: dict) -> dict:
        query = params.get("query", "")
        lang = params.get("lang", "zh")
        if not query:
            return {
                "status": "error",
                "result": None,
                "message": "No query provided.",
            }

        try:
            results = self._search_wikipedia(query, lang)
            return {
                "status": "success",
                "result": results,
                "message": f"Found {len(results)} Wikipedia results for '{query}'.",
            }
        except Exception as e:
            return {
                "status": "error",
                "result": None,
                "message": f"Wikipedia search error: {str(e)}",
            }

    def _search_wikipedia(self, query: str, lang: str) -> list[dict]:
        """Search Wikipedia API and return top results with summaries."""
        base_url = f"https://{lang}.wikipedia.org/w/api.php"

        # Step 1: Search for pages
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": 3,
            "utf8": 1,
        }
        resp = requests.get(base_url, params=search_params, timeout=15)
        resp.raise_for_status()
        search_data = resp.json()

        search_results = search_data.get("query", {}).get("search", [])
        if not search_results:
            return []

        # Step 2: Get extracts for found pages
        page_ids = [str(r["pageid"]) for r in search_results]
        extract_params = {
            "action": "query",
            "pageids": "|".join(page_ids),
            "prop": "extracts",
            "exintro": True,
            "explaintext": True,
            "exsentences": 3,
            "format": "json",
            "utf8": 1,
        }
        resp2 = requests.get(base_url, params=extract_params, timeout=15)
        resp2.raise_for_status()
        extract_data = resp2.json()

        pages = extract_data.get("query", {}).get("pages", {})
        results = []
        for pid in page_ids:
            page = pages.get(pid, {})
            title = page.get("title", "")
            extract = page.get("extract", "")
            results.append({
                "title": title,
                "summary": extract,
                "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
            })

        return results
