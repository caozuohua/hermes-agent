"""Durable gateway reset-boundary regression tests (#61220)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from gateway.config import GatewayConfig, Platform, SessionResetPolicy
from gateway.session import SessionEntry, SessionStore
from hermes_state import SessionDB


def test_promote_live_session_to_reset(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session(session_id="live", source="feishu", model="test")

        assert db.promote_to_session_reset("live", "idle") is True
        row = db.get_session("live")
        assert row["ended_at"] is not None
        assert row["end_reason"] == "idle"
    finally:
        db.close()


def test_promote_recoverable_agent_close_but_preserve_explicit_boundary(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session(session_id="cleanup", source="feishu", model="test")
        db.end_session("cleanup", "agent_close")
        assert db.promote_to_session_reset("cleanup") is True
        assert db.get_session("cleanup")["end_reason"] == "session_reset"

        db.create_session(session_id="compressed", source="feishu", model="test")
        db.end_session("compressed", "compression")
        assert db.promote_to_session_reset("compressed") is False
        assert db.get_session("compressed")["end_reason"] == "compression"
    finally:
        db.close()


def test_set_expiry_finalized_persists_json_and_promotes_db(tmp_path):
    db = MagicMock()
    config = GatewayConfig(default_reset_policy=SessionResetPolicy(mode="idle"))
    with patch("gateway.session.SessionStore._ensure_loaded"):
        store = SessionStore(sessions_dir=tmp_path, config=config)
    store._db = db
    store._loaded = True
    now = datetime.now()
    entry = SessionEntry(
        session_key="agent:main:feishu:dm:user",
        session_id="sid",
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=1),
        platform=Platform.FEISHU,
        chat_type="dm",
    )
    store._entries[entry.session_key] = entry

    store.set_expiry_finalized(entry)

    assert entry.expiry_finalized is True
    reloaded = SessionStore(sessions_dir=tmp_path, config=config)
    reloaded._db = None
    reloaded._ensure_loaded()
    assert reloaded._entries[entry.session_key].expiry_finalized is True
    db.promote_to_session_reset.assert_called_once_with("sid")
