#!/usr/bin/env python3
"""Read-only Hermes-Lite session trace exporter.

Formats recent state.db session activity for Lark/Feishu mobile reading.
The script never writes to the database.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from agent.redact import redact_sensitive_text
except Exception:  # pragma: no cover - keeps the script usable standalone.
    def redact_sensitive_text(text: str, *args: Any, **kwargs: Any) -> str:
        return text


ROLE_LABELS = {
    "user": ("👤", "User"),
    "assistant": ("🤖", "Assistant"),
    "tool": ("🛠", "Tool"),
    "system": ("⚙️", "System"),
}

ERROR_MARKERS = (
    "error",
    "exception",
    "traceback",
    "http 400",
    "http 401",
    "http 403",
    "http 413",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "rate limited",
    "failed",
)


@dataclass
class SessionRow:
    id: str
    source: str
    user_id: str
    model: str
    system_prompt: str
    parent_session_id: str
    started_at: float
    ended_at: float | None
    end_reason: str
    message_count: int
    tool_call_count: int
    input_tokens: int
    output_tokens: int
    api_call_count: int


@dataclass
class MessageRow:
    id: int
    role: str
    content: str
    tool_call_id: str
    tool_calls: str
    tool_name: str
    timestamp: float
    token_count: int
    finish_reason: str
    reasoning: str
    reasoning_content: str


def default_home() -> Path:
    raw = os.environ.get("HERMES_HOME")
    if raw:
        return Path(raw).expanduser()
    lite = Path.home() / ".hermes-lite"
    if lite.exists():
        return lite
    return Path.home() / ".hermes"


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"state.db not found: {db_path}")
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_session(conn: sqlite3.Connection, session_id: str) -> SessionRow:
    if session_id == "latest":
        row = conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"session not found: {session_id}")
    return SessionRow(
        id=row["id"],
        source=row["source"] or "",
        user_id=row["user_id"] or "",
        model=row["model"] or "",
        system_prompt=row["system_prompt"] or "",
        parent_session_id=row["parent_session_id"] or "",
        started_at=float(row["started_at"] or 0),
        ended_at=row["ended_at"],
        end_reason=row["end_reason"] or "",
        message_count=int(row["message_count"] or 0),
        tool_call_count=int(row["tool_call_count"] or 0),
        input_tokens=int(row["input_tokens"] or 0),
        output_tokens=int(row["output_tokens"] or 0),
        api_call_count=int(row["api_call_count"] or 0),
    )


def fetch_messages(
    conn: sqlite3.Connection,
    session_id: str,
    limit: int,
) -> tuple[list[MessageRow], int]:
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE session_id = ? AND active = 1",
        (session_id,),
    ).fetchone()["n"]
    rows = conn.execute(
        """
        SELECT * FROM messages
        WHERE session_id = ? AND active = 1
        ORDER BY timestamp ASC, id ASC
        LIMIT ? OFFSET ?
        """,
        (session_id, limit, max(0, total - limit)),
    ).fetchall()
    messages = [
        MessageRow(
            id=int(row["id"]),
            role=row["role"] or "",
            content=row["content"] or "",
            tool_call_id=row["tool_call_id"] or "",
            tool_calls=row["tool_calls"] or "",
            tool_name=row["tool_name"] or "",
            timestamp=float(row["timestamp"] or 0),
            token_count=int(row["token_count"] or 0),
            finish_reason=row["finish_reason"] or "",
            reasoning=row["reasoning"] or "",
            reasoning_content=row["reasoning_content"] or "",
        )
        for row in rows
    ]
    return messages, int(total)


def list_sessions(conn: sqlite3.Connection, limit: int) -> str:
    rows = conn.execute(
        """
        SELECT id, source, model, message_count, tool_call_count, started_at
        FROM sessions
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    lines = ["🔎 **Hermes-Lite Sessions**"]
    for row in rows:
        started = fmt_time(row["started_at"])
        lines.append("")
        lines.append(f"🟢 `{row['id']}`")
        lines.append(f"   时间: {started}")
        lines.append(f"   来源: `{row['source'] or '-'}`")
        lines.append(f"   模型: `{row['model'] or '-'}`")
        lines.append(
            f"   消息/工具: {row['message_count'] or 0} / {row['tool_call_count'] or 0}"
        )
    return "\n".join(lines)


def fmt_time(value: float | int | None) -> str:
    if not value:
        return "-"
    return datetime.fromtimestamp(float(value)).strftime("%m-%d %H:%M:%S")


def clean_text(text: str, max_chars: int) -> str:
    text = redact_sensitive_text(text or "", force=True)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max(0, max_chars - 20)].rstrip() + "\n...[truncated]"
    return text or "(empty)"


def wrapped_block(text: str, *, indent: str = "   ", width: int = 72) -> list[str]:
    out: list[str] = []
    for raw_line in text.splitlines() or [""]:
        line = raw_line.strip()
        if not line:
            out.append("")
            continue
        chunks = textwrap.wrap(
            line,
            width=width,
            break_long_words=False,
            break_on_hyphens=False,
        ) or [line]
        out.extend(indent + chunk for chunk in chunks)
    return out


def parse_tool_calls(raw: str) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def tool_call_name(call: dict[str, Any]) -> str:
    fn = call.get("function")
    if isinstance(fn, dict):
        return str(fn.get("name") or "").strip()
    return str(call.get("name") or "").strip()


def extract_error_hint(message: MessageRow) -> str:
    content = message.content or ""
    parsed: Any = None
    if content.strip().startswith(("{", "[")):
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = None
    if isinstance(parsed, dict):
        for key in ("error", "message", "status"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                if key == "status" and value.lower() not in {"error", "failed"}:
                    continue
                return value.strip()
        nested = parsed.get("output")
        if isinstance(nested, str) and any(m in nested.lower() for m in ERROR_MARKERS):
            return nested.strip()
    lowered = content.lower()
    if any(marker in lowered for marker in ERROR_MARKERS):
        first = next((line.strip() for line in content.splitlines() if line.strip()), content)
        return first
    return ""


def rough_tokens(messages: list[MessageRow], session: SessionRow) -> int:
    stored = sum(m.token_count for m in messages if m.token_count > 0)
    if stored:
        return stored
    chars = len(session.system_prompt or "") + sum(len(m.content or "") for m in messages)
    chars += sum(len(m.tool_calls or "") + len(m.reasoning or "") for m in messages)
    return max(1, chars // 4)


def render_trace(
    session: SessionRow,
    messages: list[MessageRow],
    *,
    total_messages: int,
    max_chars: int,
    include_system: bool,
) -> str:
    tool_call_messages = [m for m in messages if parse_tool_calls(m.tool_calls)]
    tool_results = [m for m in messages if m.role == "tool"]
    errors = [(m, extract_error_hint(m)) for m in messages]
    errors = [(m, hint) for m, hint in errors if hint]
    shown_from = max(1, total_messages - len(messages) + 1) if messages else 0
    approx_tokens = rough_tokens(messages, session)

    lines: list[str] = []
    lines.append("🔎 **Hermes-Lite Trace**")
    lines.append("")
    lines.append(f"🟢 **Session** `{session.id}`")
    lines.append(f"   来源: `{session.source or '-'}`")
    lines.append(f"   模型: `{session.model or '-'}`")
    lines.append(f"   时间: {fmt_time(session.started_at)} → {fmt_time(session.ended_at)}")
    lines.append(f"   结束: `{session.end_reason or 'running/unknown'}`")
    lines.append("")
    lines.append("🧮 **概览**")
    lines.append(f"   消息: {total_messages} 条，显示 {shown_from}-{total_messages}")
    lines.append(f"   工具调用: session 记录 {session.tool_call_count} 次")
    lines.append(f"   当前片段工具结果: {len(tool_results)} 条")
    lines.append(f"   当前片段粗估 tokens: ~{approx_tokens:,}")
    if session.input_tokens or session.output_tokens:
        lines.append(
            f"   账单 tokens: input {session.input_tokens:,} / output {session.output_tokens:,}"
        )
    lines.append(f"   system prompt: {len(session.system_prompt or ''):,} chars")

    if errors:
        lines.append("")
        lines.append("🟡 **错误/告警线索**")
        for idx, (msg, hint) in enumerate(errors[:5], 1):
            icon, label = ROLE_LABELS.get(msg.role, ("▫️", msg.role or "unknown"))
            short = clean_text(hint, 220).replace("\n", " ")
            lines.append(f"   {idx}. {icon} {label} #{msg.id}: {short}")
        if len(errors) > 5:
            lines.append(f"   其余 {len(errors) - 5} 条已省略")

    if include_system and session.system_prompt:
        lines.append("")
        lines.append("⚙️ **System Prompt Preview**")
        lines.extend(wrapped_block(clean_text(session.system_prompt, max_chars)))

    lines.append("")
    lines.append("📜 **Timeline**")
    for idx, msg in enumerate(messages, 1):
        icon, label = ROLE_LABELS.get(msg.role, ("▫️", msg.role or "unknown"))
        token_part = f", ~{msg.token_count:,} tok" if msg.token_count else ""
        tool_suffix = f" `{msg.tool_name}`" if msg.role == "tool" and msg.tool_name else ""
        lines.append("")
        lines.append(
            f"{idx}. {icon} **{label}{tool_suffix}** #{msg.id} "
            f"{fmt_time(msg.timestamp)}{token_part}"
        )
        calls = parse_tool_calls(msg.tool_calls)
        if calls:
            names = [name for name in (tool_call_name(call) for call in calls) if name]
            if names:
                lines.append(f"   决策动作: {', '.join(f'`{name}`' for name in names)}")
        if msg.finish_reason:
            lines.append(f"   finish: `{msg.finish_reason}`")
        if msg.reasoning or msg.reasoning_content:
            rchars = len(msg.reasoning or "") + len(msg.reasoning_content or "")
            lines.append(f"   reasoning: {rchars:,} chars captured")
        preview = clean_text(msg.content, max_chars)
        lines.extend(wrapped_block(preview))

    lines.append("")
    lines.append("📌 **说明**")
    lines.append("   只读导出 state.db；内容已做 Hermes secret redaction。")
    lines.append("   tokens 为粗估；完整 API wire payload 默认没有保存。")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a read-only Hermes-Lite session trace for Lark mobile.",
    )
    parser.add_argument("--home", type=Path, default=None, help="Hermes home directory")
    parser.add_argument("--db", type=Path, default=None, help="Path to state.db")
    parser.add_argument("--session", default="latest", help="Session id or 'latest'")
    parser.add_argument("--messages", type=int, default=24, help="Tail messages to show")
    parser.add_argument("--chars", type=int, default=700, help="Max chars per message")
    parser.add_argument("--include-system", action="store_true", help="Show system prompt preview")
    parser.add_argument("--list", action="store_true", help="List recent sessions")
    parser.add_argument("--list-limit", type=int, default=8, help="Recent sessions to list")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = (args.home or default_home()).expanduser()
    db_path = (args.db or (home / "state.db")).expanduser()
    if args.messages <= 0:
        raise SystemExit("--messages must be > 0")
    if args.chars < 80:
        raise SystemExit("--chars must be >= 80")

    conn = connect_readonly(db_path)
    try:
        if args.list:
            print(list_sessions(conn, args.list_limit))
            return 0
        session = fetch_session(conn, args.session)
        messages, total = fetch_messages(conn, session.id, args.messages)
        print(
            render_trace(
                session,
                messages,
                total_messages=total,
                max_chars=args.chars,
                include_system=args.include_system,
            )
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
