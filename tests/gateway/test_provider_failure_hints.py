import time

from gateway.run import GatewayRunner


def _runner():
    runner = object.__new__(GatewayRunner)
    runner._session_provider_failures = {}
    return runner


def test_provider_failure_note_is_one_shot():
    runner = _runner()
    runner._record_session_provider_failure(
        "session-1",
        {
            "provider": "newapi-local",
            "model": "stepfun-ai/step-3.7-flash",
            "reason": "overloaded",
            "status_code": 503,
            "summary": "system cpu overloaded",
            "recorded_at": time.time(),
        },
    )

    note = runner._consume_session_provider_failure_note("session-1")

    assert "previous LLM turn hit a provider failure" in note
    assert "overloaded HTTP 503" in note
    assert "newapi-local/stepfun-ai/step-3.7-flash" in note
    assert runner._consume_session_provider_failure_note("session-1") == ""


def test_provider_failure_note_ignores_stale_state():
    runner = _runner()
    runner._record_session_provider_failure(
        "session-1",
        {
            "provider": "newapi-local",
            "model": "stepfun-ai/step-3.7-flash",
            "reason": "rate_limit",
            "recorded_at": time.time() - 901,
        },
    )

    assert runner._consume_session_provider_failure_note("session-1") == ""
    assert "session-1" not in runner._session_provider_failures
