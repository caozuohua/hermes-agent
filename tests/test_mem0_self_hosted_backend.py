from __future__ import annotations

import json
import threading

import httpx

from plugins.memory.mem0 import Mem0MemoryProvider
from plugins.memory.mem0._backend import SelfHostedBackend


def test_self_hosted_backend_uses_long_write_timeout_and_run_id() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": []})

    backend = SelfHostedBackend(
        "secret",
        "http://mem0.test",
        transport=httpx.MockTransport(handler),
    )
    try:
        backend.add(
            [{"role": "user", "content": "remember this"}],
            user_id="personal",
            agent_id="gcp-hermes",
            infer=True,
            run_id="session-123",
        )
    finally:
        backend.close()

    assert backend._client.timeout.read == 60.0
    assert captured["body"]["run_id"] == "session-123"


def test_sync_turn_uses_session_id_as_idempotency_scope() -> None:
    called = threading.Event()
    captured: dict = {}

    class Backend:
        def add(self, messages, **kwargs):
            captured.update(kwargs)
            called.set()
            return {"results": []}

    provider = Mem0MemoryProvider()
    provider._backend = Backend()
    provider._user_id = "personal"
    provider._agent_id = "gcp-hermes"

    provider.sync_turn("hello", "world", session_id="session-456")

    assert called.wait(timeout=1.0)
    assert captured["run_id"] == "session-456"
