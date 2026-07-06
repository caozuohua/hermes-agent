"""Gemini Grounding with Google Search provider.

This provider adapts Gemini's answer-oriented Google Search grounding into the
Hermes ``web_search`` response shape. It intentionally does not implement
``web_extract``: Gemini returns a grounded answer plus citations, not a stable
SERP or raw page extraction API.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx

from agent.web_search_provider import WebSearchProvider


_DEFAULT_MODEL = "gemini-2.5-flash-lite"
_DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"


def _gemini_api_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def _gemini_model() -> str:
    return (os.getenv("GEMINI_GROUNDED_MODEL") or _DEFAULT_MODEL).strip()


def _gemini_endpoint() -> str:
    return (os.getenv("GEMINI_GROUNDED_ENDPOINT") or _DEFAULT_ENDPOINT).strip()


def _collect_citations(response: Dict[str, Any]) -> List[Dict[str, str]]:
    citations: List[Dict[str, str]] = []
    seen: set[str] = set()
    for step in response.get("steps") or []:
        for content in step.get("content") or []:
            for annotation in content.get("annotations") or []:
                if annotation.get("type") != "url_citation":
                    continue
                url = (annotation.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                citations.append({
                    "title": annotation.get("title") or url,
                    "url": url,
                    "description": annotation.get("cited_text") or "",
                })
    return citations


def _output_text(response: Dict[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    parts: List[str] = []
    for step in response.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for content in step.get("content") or []:
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
    return "\n".join(parts)


def _normalize_gemini_grounded_response(response: Dict[str, Any], model: str) -> Dict[str, Any]:
    answer = _output_text(response)
    web_results = []
    for index, citation in enumerate(_collect_citations(response), start=1):
        web_results.append({
            "title": citation["title"],
            "url": citation["url"],
            "description": citation["description"],
            "position": index,
        })
    return {
        "success": True,
        "data": {
            "answer": answer,
            "web": web_results,
            "strategy": {
                "backend": "gemini-grounded",
                "model": model,
                "tool": "google_search",
            },
        },
    }


class GeminiGroundedWebSearchProvider(WebSearchProvider):
    """Answer-oriented Google Search grounding through Gemini."""

    @property
    def name(self) -> str:
        return "gemini-grounded"

    @property
    def display_name(self) -> str:
        return "Gemini Grounded Search"

    def is_available(self) -> bool:
        return bool(_gemini_api_key())

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return False

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        try:
            from tools.interrupt import is_interrupted

            if is_interrupted():
                return {"success": False, "error": "Interrupted"}

            api_key = _gemini_api_key()
            if not api_key:
                return {
                    "success": False,
                    "error": "GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set.",
                }
            model = _gemini_model()
            response = httpx.post(
                _gemini_endpoint(),
                headers={
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": query,
                    "tools": [{"type": "google_search"}],
                },
                timeout=60,
            )
            response.raise_for_status()
            return _normalize_gemini_grounded_response(response.json(), model)
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": f"Gemini grounded search failed: {exc}"}

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Gemini Grounded Search",
            "badge": "google",
            "tag": "Google Search grounding via Gemini. Uses GEMINI_API_KEY or GOOGLE_API_KEY.",
            "env_vars": [
                {
                    "key": "GEMINI_API_KEY",
                    "prompt": "Google AI Studio / Gemini API key",
                    "url": "https://aistudio.google.com/apikey",
                },
            ],
        }
