from gateway.run import _redact_approval_command


def test_redact_approval_command_forces_secret_redaction(monkeypatch):
    monkeypatch.setattr("agent.redact._REDACT_ENABLED", False)

    command = "echo sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
    redacted = _redact_approval_command(command)

    assert "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789" not in redacted
    assert "..." in redacted
