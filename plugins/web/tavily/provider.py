"""Tavily web search + content extraction — plugin form.

Subclasses :class:`agent.web_search_provider.WebSearchProvider`. Two
capabilities advertised:

- ``supports_search()``  -> True (Tavily ``/search``)
- ``supports_extract()`` -> True (Tavily ``/extract``)

Both are sync — the underlying call is ``httpx.post(...)``.

Config keys this provider responds to::

    web:
      search_backend: "tavily"     # explicit per-capability
      extract_backend: "tavily"    # explicit per-capability
      backend: "tavily"            # shared fallback for both

Env vars::

    TAVILY_API_KEY=...           # https://app.tavily.com/home (required)
    TAVILY_BASE_URL=...          # optional override of https://api.tavily.com
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


def _tavily_request(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST to the Tavily API and return the parsed JSON response.

    Mirrors :func:`tools.web_tools._tavily_request`. Raises ``ValueError``
    when ``TAVILY_API_KEY`` is unset; the caller catches and surfaces as
    a typed error response.
    """
    import httpx

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError(
            "TAVILY_API_KEY environment variable not set. "
            "Get your API key at https://app.tavily.com/home"
        )

    base_url = os.getenv("TAVILY_BASE_URL", "https://api.tavily.com")
    payload = dict(payload)  # don't mutate caller's dict
    payload["api_key"] = api_key
    url = f"{base_url}/{endpoint.lstrip('/')}"
    logger.info("Tavily %s request to %s", endpoint, url)

    response = httpx.post(url, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def _normalize_tavily_search_results(response: Dict[str, Any]) -> Dict[str, Any]:
    """Map Tavily ``/search`` response to ``{success, data: {web: [...]}}``."""
    web_results = []
    for i, result in enumerate(response.get("results", [])):
        normalized = {
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "description": result.get("content", ""),
            "position": i + 1,
        }
        if result.get("published_date"):
            normalized["published_date"] = result.get("published_date")
        if result.get("score") is not None:
            normalized["score"] = result.get("score")
        web_results.append(normalized)
    return {"success": True, "data": {"web": web_results}}


def _normalize_tavily_documents(
    response: Dict[str, Any], fallback_url: str = ""
) -> List[Dict[str, Any]]:
    """Map Tavily ``/extract`` response to standard documents.

    Documents follow the legacy LLM post-processing shape::

        {"url", "title", "content", "raw_content", "metadata"}

    Failures (``failed_results``, ``failed_urls``) become result entries
    with an ``error`` field rather than raising.
    """
    documents: List[Dict[str, Any]] = []
    for result in response.get("results", []):
        url = result.get("url", fallback_url)
        raw = result.get("raw_content", "") or result.get("content", "")
        documents.append(
            {
                "url": url,
                "title": result.get("title", ""),
                "content": raw,
                "raw_content": raw,
                "metadata": {"sourceURL": url, "title": result.get("title", "")},
            }
        )
    for fail in response.get("failed_results", []):
        documents.append(
            {
                "url": fail.get("url", fallback_url),
                "title": "",
                "content": "",
                "raw_content": "",
                "error": fail.get("error", "extraction failed"),
                "metadata": {"sourceURL": fail.get("url", fallback_url)},
            }
        )
    for fail_url in response.get("failed_urls", []):
        url_str = fail_url if isinstance(fail_url, str) else str(fail_url)
        documents.append(
            {
                "url": url_str,
                "title": "",
                "content": "",
                "raw_content": "",
                "error": "extraction failed",
                "metadata": {"sourceURL": url_str},
            }
        )
    return documents


class TavilyWebSearchProvider(WebSearchProvider):
    """Tavily search + extract provider."""

    _LIVE_SPORTS_DOMAINS = [
        "fifa.com",
        "espn.com",
        "cbssports.com",
        "foxsports.com",
        "bbc.com",
        "reuters.com",
        "theguardian.com",
    ]

    @property
    def name(self) -> str:
        return "tavily"

    @property
    def display_name(self) -> str:
        return "Tavily"

    def is_available(self) -> bool:
        """Return True when ``TAVILY_API_KEY`` is set to a non-empty value."""
        return bool(os.getenv("TAVILY_API_KEY", "").strip())

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    @staticmethod
    def _search_plan(query: str, limit: int) -> Dict[str, Any]:
        """Choose a cost-aware Tavily plan without exposing more tool schema.

        Default to cheap/basic searches with fewer snippets. Escalate only
        when the query itself asks for freshness or deeper comparison.
        """
        q = (query or "").strip()
        q_lower = q.lower()
        wants_news = bool(
            re.search(
                r"\b(today|yesterday|latest|recent|breaking|news|this week|"
                r"last week|202[5-9]|current)\b",
                q_lower,
            )
            or any(term in q for term in ("今天", "昨天", "最新", "最近", "新闻", "实时", "本周", "本月"))
        )
        wants_depth = bool(
            re.search(
                r"\b(compare|comparison|versus|vs\.?|benchmark|deep dive|"
                r"analysis|tradeoff|survey|review|why|how)\b",
                q_lower,
            )
            or any(term in q for term in ("对比", "比较", "深入", "详细", "分析", "综述", "论文", "评测", "为什么", "如何"))
        )
        wants_live_sports = bool(
            (
                re.search(
                    r"\b(fifa|world cup|soccer|football|score|scores|"
                    r"fixture|fixtures|schedule|standings|match|matches)\b",
                    q_lower,
                )
                or any(term in q for term in ("世界杯", "足球", "赛程", "赛况", "比分", "实况", "直播", "比赛"))
            )
            and (
                wants_news
                or re.search(r"\b(live|score|scores|today|current|now)\b", q_lower)
                or any(term in q for term in ("实时", "今天", "今日", "赛况", "比分", "实况", "直播"))
            )
        )

        if wants_live_sports:
            depth = "basic"
            max_results = min(max(limit, 5), 8)
            include_answer = "basic"
        elif wants_depth:
            depth = "advanced"
            max_results = min(max(limit, 3), 5)
            include_answer: Any = False
        elif wants_news:
            depth = "basic"
            max_results = min(max(limit, 3), 5)
            include_answer = "basic"
        else:
            depth = "basic"
            max_results = min(max(limit, 1), 3)
            include_answer = "basic"

        plan: Dict[str, Any] = {
            "search_depth": depth,
            "max_results": max_results,
            "include_answer": include_answer,
            "include_raw_content": False,
            "include_images": False,
        }
        if wants_live_sports:
            plan["topic"] = "news"
            plan["time_range"] = "day"
            plan["days"] = 2
            plan["include_domains"] = list(TavilyWebSearchProvider._LIVE_SPORTS_DOMAINS)
            plan["intent"] = "live_sports"
            if "世界杯" in q:
                plan["_query_suffix"] = "FIFA World Cup live scores fixtures today"
            elif any(term in q for term in ("足球", "赛程", "赛况", "比分", "实况", "直播", "比赛")):
                plan["_query_suffix"] = "live scores fixtures today"
            return plan
        if wants_news:
            plan["topic"] = "news"
            plan["days"] = 7
            plan["time_range"] = "week"
        return plan

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Execute a Tavily search."""
        try:
            from tools.interrupt import is_interrupted

            if is_interrupted():
                return {"success": False, "error": "Interrupted"}

            plan = self._search_plan(query, limit)
            logger.info(
                "Tavily search: '%s' (depth=%s, topic=%s, limit=%d)",
                query,
                plan.get("search_depth"),
                plan.get("topic", "general"),
                plan.get("max_results"),
            )
            query_suffix = plan.pop("_query_suffix", "")
            search_query = query
            query_expanded = False
            if query_suffix and query_suffix.lower() not in (query or "").lower():
                search_query = f"{query} {query_suffix}".strip()
                query_expanded = True

            raw = _tavily_request("search", {"query": search_query, **plan})
            domain_retry = False
            if plan.get("include_domains") and not raw.get("results"):
                relaxed_plan = dict(plan)
                relaxed_plan.pop("include_domains", None)
                raw = _tavily_request("search", {"query": search_query, **relaxed_plan})
                plan = relaxed_plan
                domain_retry = True
            normalized = _normalize_tavily_search_results(raw)
            if raw.get("answer"):
                normalized.setdefault("data", {})["answer"] = raw.get("answer")
            strategy = {
                "backend": "tavily",
                "search_depth": plan.get("search_depth"),
                "topic": plan.get("topic", "general"),
                "days": plan.get("days"),
                "time_range": plan.get("time_range"),
                "max_results": plan.get("max_results"),
            }
            if plan.get("include_domains"):
                strategy["include_domains"] = plan.get("include_domains")
            if plan.get("intent"):
                strategy["intent"] = plan.get("intent")
            if query_expanded:
                strategy["query_expanded"] = True
            if domain_retry:
                strategy["domain_retry"] = True
            normalized.setdefault("data", {})["strategy"] = strategy
            return normalized
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — including httpx errors
            logger.warning("Tavily search error: %s", exc)
            return {"success": False, "error": f"Tavily search failed: {exc}"}

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        """Extract content from one or more URLs via Tavily.

        Sync — the underlying call is httpx.post(...). Returns the legacy
        list-of-results shape; per-URL failures become items with ``error``.
        """
        try:
            from tools.interrupt import is_interrupted

            if is_interrupted():
                return [
                    {"url": u, "error": "Interrupted", "title": ""} for u in urls
                ]

            logger.info("Tavily extract: %d URL(s)", len(urls))
            raw = _tavily_request(
                "extract",
                {
                    "urls": urls,
                    "include_images": False,
                },
            )
            return _normalize_tavily_documents(
                raw, fallback_url=urls[0] if urls else ""
            )
        except ValueError as exc:
            return [{"url": u, "title": "", "content": "", "error": str(exc)} for u in urls]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tavily extract error: %s", exc)
            return [
                {"url": u, "title": "", "content": "", "error": f"Tavily extract failed: {exc}"}
                for u in urls
            ]

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Tavily",
            "badge": "paid",
            "tag": "Search + extract in one provider.",
            "env_vars": [
                {
                    "key": "TAVILY_API_KEY",
                    "prompt": "Tavily API key",
                    "url": "https://app.tavily.com/home",
                },
            ],
        }
