"""HermesLite gateway slash command rendering."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource, build_session_key


def _source() -> SessionSource:
    return SessionSource(
        platform=Platform.FEISHU,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _event(text: str) -> MessageEvent:
    return MessageEvent(text=text, source=_source(), message_id="m1")


def _runner():
    from gateway.run import GatewayRunner

    session_entry = SessionEntry(
        session_key=build_session_key(_source()),
        session_id="sess-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.FEISHU,
        chat_type="dm",
        total_tokens=0,
    )
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.FEISHU: PlatformConfig(enabled=True, token="***")}
    )
    runner.adapters = {Platform.FEISHU: MagicMock()}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = session_entry
    runner._running_agents = {}
    runner._agent_cache = {}
    runner._agent_cache_lock = MagicMock()
    runner._session_db = MagicMock()
    runner._session_db.get_session_title.return_value = None
    runner._session_db.get_session.return_value = None
    return runner


@pytest.fixture
def lite_config(monkeypatch):
    cfg = {
        "gateway": {"lite_commands": True, "service_name": "hermes-lite.service"},
        "model": {
            "default": "MiniMax-M3",
            "provider": "custom",
            "base_url": "https://api.tokenrouter.com/v1",
        },
        "agent": {
            "disabled_toolsets": ["browser", "image_gen", "tts", "computer_use"]
        },
    }
    monkeypatch.setattr("gateway.run._load_gateway_config", lambda: cfg)
    return cfg


@pytest.mark.asyncio
async def test_lite_help_is_small_allowlist_and_includes_goal(lite_config):
    result = await _runner()._handle_help_command(_event("/help"))

    assert "/goal" in result
    assert "/status" in result
    assert "/model" in result
    assert "/voice" not in result
    assert "/codex-runtime" not in result
    assert "/rollback" not in result
    assert len(result) < 1200


@pytest.mark.asyncio
async def test_lite_model_without_args_reports_current_model_only(lite_config):
    result = await _runner()._handle_model_command(_event("/model"))

    assert "MiniMax-M3" in result
    assert "custom" in result
    assert "--provider" not in result
    assert "Available" not in result
    assert len(result) < 700


@pytest.mark.asyncio
async def test_lite_status_reports_runtime_not_session_cockpit(lite_config):
    result = await _runner()._handle_status_command(_event("/status"))

    assert "HermesLite" in result
    assert "hermes-lite.service" in result
    assert "MiniMax-M3" in result
    assert "browser, image_gen, tts, computer_use" in result
    assert "Session ID" not in result
    assert "Cumulative API tokens" not in result
    assert len(result) < 1000
