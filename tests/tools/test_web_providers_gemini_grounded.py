import json
import os
from unittest.mock import MagicMock, patch


class TestGeminiGroundedProvider:
    def test_available_with_gemini_or_google_api_key(self, monkeypatch):
        from plugins.web.gemini_grounded.provider import GeminiGroundedWebSearchProvider

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        provider = GeminiGroundedWebSearchProvider()
        assert provider.is_available() is False

        monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
        assert provider.is_available() is True

    def test_posts_to_interactions_with_google_search_tool(self, monkeypatch):
        from plugins.web.gemini_grounded.provider import GeminiGroundedWebSearchProvider

        monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "output_text": "Brazil beat Norway 2-1.",
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "text",
                            "text": "Brazil beat Norway 2-1.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://www.fifa.com/match-centre",
                                    "title": "FIFA Match Centre",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("plugins.web.gemini_grounded.provider.httpx.post", return_value=mock_response) as mock_post:
            result = GeminiGroundedWebSearchProvider().search("Brazil Norway score", limit=3)

        assert result["success"] is True
        assert result["data"]["answer"] == "Brazil beat Norway 2-1."
        assert result["data"]["web"][0]["url"] == "https://www.fifa.com/match-centre"
        assert result["data"]["web"][0]["title"] == "FIFA Match Centre"
        assert result["data"]["strategy"]["backend"] == "gemini-grounded"

        url = mock_post.call_args.args[0]
        payload = mock_post.call_args.kwargs["json"]
        headers = mock_post.call_args.kwargs["headers"]
        assert url == "https://generativelanguage.googleapis.com/v1beta/interactions"
        assert headers["x-goog-api-key"] == "gemini-key"
        assert payload["tools"] == [{"type": "google_search"}]

    def test_uses_model_output_text_when_output_text_missing(self, monkeypatch):
        from plugins.web.gemini_grounded.provider import _normalize_gemini_grounded_response

        result = _normalize_gemini_grounded_response(
            {
                "steps": [
                    {
                        "type": "model_output",
                        "content": [
                            {
                                "type": "text",
                                "text": "Answer from model output step.",
                                "annotations": [],
                            }
                        ],
                    }
                ]
            },
            "gemini-2.5-flash-lite",
        )

        assert result["data"]["answer"] == "Answer from model output step."


class TestGeminiGroundedIntegration:
    def test_backend_availability_uses_gemini_api_key(self, monkeypatch):
        from tools import web_tools

        monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
        assert web_tools._is_backend_available("gemini-grounded") is True

    def test_web_search_dispatches_to_gemini_grounded(self, monkeypatch):
        from tests.tools.conftest import register_all_web_providers
        from tools import web_tools

        register_all_web_providers()
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
        monkeypatch.setattr(web_tools, "_load_web_config", lambda: {"search_backend": "gemini-grounded"})

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "output_text": "Grounded answer.",
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "text",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.com/source",
                                    "title": "Example Source",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("plugins.web.gemini_grounded.provider.httpx.post", return_value=mock_response):
            result = json.loads(web_tools.web_search_tool("latest news", limit=2))

        assert result["success"] is True
        assert result["data"]["answer"] == "Grounded answer."
        assert result["data"]["strategy"]["backend"] == "gemini-grounded"
