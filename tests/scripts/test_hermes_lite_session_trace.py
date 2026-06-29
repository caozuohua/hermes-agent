import sqlite3
from pathlib import Path

from scripts.hermes_lite_session_trace import (
    connect_readonly,
    fetch_messages,
    fetch_session,
    list_sessions,
    render_trace,
)


def _make_state_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            user_id TEXT,
            model TEXT,
            model_config TEXT,
            system_prompt TEXT,
            parent_session_id TEXT,
            started_at REAL NOT NULL,
            ended_at REAL,
            end_reason TEXT,
            message_count INTEGER DEFAULT 0,
            tool_call_count INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_write_tokens INTEGER DEFAULT 0,
            reasoning_tokens INTEGER DEFAULT 0,
            cwd TEXT,
            billing_provider TEXT,
            billing_base_url TEXT,
            billing_mode TEXT,
            estimated_cost_usd REAL,
            actual_cost_usd REAL,
            cost_status TEXT,
            cost_source TEXT,
            pricing_version TEXT,
            title TEXT,
            api_call_count INTEGER DEFAULT 0,
            handoff_state TEXT,
            handoff_platform TEXT,
            handoff_error TEXT,
            rewind_count INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            tool_name TEXT,
            timestamp REAL NOT NULL,
            token_count INTEGER,
            finish_reason TEXT,
            reasoning TEXT,
            reasoning_content TEXT,
            reasoning_details TEXT,
            codex_reasoning_items TEXT,
            codex_message_items TEXT,
            platform_message_id TEXT,
            observed INTEGER DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    conn.execute(
        """
        INSERT INTO sessions (
            id, source, user_id, model, system_prompt, started_at, ended_at,
            end_reason, message_count, tool_call_count, input_tokens,
            output_tokens, api_call_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "s_latest",
            "feishu",
            "ou_user",
            "openrouter/owl-alpha",
            "system prompt with sk-test_abcdefghijklmnopqrstuvwxyz",
            2000.0,
            None,
            "",
            4,
            1,
            100,
            20,
            2,
        ),
    )
    conn.execute(
        """
        INSERT INTO sessions (
            id, source, user_id, model, system_prompt, started_at, message_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("s_old", "feishu", "ou_user", "old-model", "old", 1000.0, 1),
    )
    rows = [
        (
            1,
            "s_latest",
            "user",
            "帮我检查服务",
            "",
            "",
            "",
            2001.0,
            0,
            "",
            "",
            "",
        ),
        (
            2,
            "s_latest",
            "assistant",
            "",
            "",
            '[{"function":{"name":"terminal","arguments":"{\\"command\\":\\"systemctl status hermes-lite\\"}"}}]',
            "",
            2002.0,
            0,
            "tool_calls",
            "hidden reasoning",
            "",
        ),
        (
            3,
            "s_latest",
            "tool",
            '{"output":"boom","exit_code":1,"error":"HTTP 400: Provider returned error"}',
            "call_1",
            "",
            "terminal",
            2003.0,
            0,
            "",
            "",
            "",
        ),
        (
            4,
            "s_latest",
            "assistant",
            "服务有错误，token=sk-test_abcdefghijklmnopqrstuvwxyz",
            "",
            "",
            "",
            2004.0,
            12,
            "stop",
            "",
            "",
        ),
    ]
    conn.executemany(
        """
        INSERT INTO messages (
            id, session_id, role, content, tool_call_id, tool_calls, tool_name,
            timestamp, token_count, finish_reason, reasoning, reasoning_content
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def test_render_latest_trace_for_lark_mobile(tmp_path):
    db = tmp_path / "state.db"
    _make_state_db(db)
    conn = connect_readonly(db)
    try:
        session = fetch_session(conn, "latest")
        messages, total = fetch_messages(conn, session.id, 10)
        out = render_trace(
            session,
            messages,
            total_messages=total,
            max_chars=300,
            include_system=True,
        )
    finally:
        conn.close()

    assert "🔎 **Hermes-Lite Trace**" in out
    assert "🟢 **Session** `s_latest`" in out
    assert "决策动作: `terminal`" in out
    assert "🟡 **错误/告警线索**" in out
    assert "HTTP 400: Provider returned error" in out
    assert "sk-test_abcdefghijklmnopqrstuvwxyz" not in out
    assert "|------" not in out


def test_list_sessions_uses_mobile_blocks(tmp_path):
    db = tmp_path / "state.db"
    _make_state_db(db)
    conn = connect_readonly(db)
    try:
        out = list_sessions(conn, 2)
    finally:
        conn.close()

    assert "🔎 **Hermes-Lite Sessions**" in out
    assert "`s_latest`" in out
    assert "`s_old`" in out
    assert "|" not in out
