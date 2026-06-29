from pathlib import Path


def test_feishu_ws_client_does_not_enable_info_sdk_logs():
    for path in (
        Path("gateway/platforms/feishu.py"),
        Path("plugins/platforms/feishu/adapter.py"),
    ):
        source = path.read_text(encoding="utf-8")
        assert "log_level=lark.LogLevel.WARNING" in source
        assert "log_level=lark.LogLevel.INFO" not in source
