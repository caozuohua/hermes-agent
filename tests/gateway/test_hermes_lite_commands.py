"""HermesLite gateway slash command rendering."""

from datetime import datetime
import threading
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
    assert "Memory:" in result
    assert "Disk:" in result
    assert "Disabled toolsets" not in result
    assert "browser, image_gen, tts, computer_use" not in result
    assert "Session ID" not in result
    assert "Cumulative API tokens" not in result
    assert len(result) < 1000


@pytest.mark.asyncio
async def test_lite_usage_uses_plain_labels_not_i18n_keys(lite_config):
    runner = _runner()
    agent = MagicMock()
    agent.model = "MiniMax-M3"
    agent.session_api_calls = 2
    agent.session_total_tokens = 1234
    agent.session_input_tokens = 900
    agent.session_output_tokens = 334
    agent.session_cache_read_tokens = 0
    agent.session_cache_write_tokens = 0
    agent.get_rate_limit_state.return_value = None
    agent.context_compressor = SimpleNamespace(
        last_prompt_tokens=0,
        context_length=1_000_000,
        compression_count=0,
    )
    runner._agent_cache_lock = threading.Lock()
    runner._agent_cache = {build_session_key(_source()): (agent, "sig")}

    result = await runner._handle_usage_command(_event("/usage"))

    assert "HermesLite usage" in result
    assert "Model: `MiniMax-M3`" in result
    assert "Input tokens: 900" in result
    assert "Output tokens: 334" in result
    assert "Total tokens: 1,234" in result
    assert "API calls: 2" in result
    assert "gateway.usage" not in result


@pytest.mark.asyncio
async def test_lite_new_uses_plain_header_not_i18n_keys(lite_config):
    runner = _runner()
    session_key = build_session_key(_source())
    old_entry = runner.session_store.get_or_create_session.return_value
    new_entry = SessionEntry(
        session_key=session_key,
        session_id="sess-2",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.FEISHU,
        chat_type="dm",
        total_tokens=0,
    )
    runner.session_store._entries = {session_key: old_entry}
    runner.session_store.reset_session.return_value = new_entry
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._session_model_overrides = {}
    runner._pending_model_notes = {}
    runner._background_tasks = set()
    runner._format_session_info = lambda: "\n".join(
        [
            "◆ Model: `MiniMax-M3`",
            "◆ Provider: custom",
            "◆ Context: 1.0M tokens (detected)",
        ]
    )

    result = await runner._handle_reset_command(_event("/new"))
    text = str(result)

    assert "HermesLite session reset" in text
    assert "◆ Model: `MiniMax-M3`" in text
    assert "gateway.reset" not in text
