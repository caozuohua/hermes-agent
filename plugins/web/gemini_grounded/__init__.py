"""Gemini Grounding with Google Search provider plugin."""

from __future__ import annotations

from plugins.web.gemini_grounded.provider import GeminiGroundedWebSearchProvider


def register(ctx) -> None:
    """Register the Gemini grounded web-search provider."""
    ctx.register_web_search_provider(GeminiGroundedWebSearchProvider())
