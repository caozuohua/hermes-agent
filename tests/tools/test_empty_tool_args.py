import json

from tools.file_tools import READ_FILE_SCHEMA, _handle_read_file
from tools.terminal_tool import TERMINAL_SCHEMA, terminal_tool


def test_terminal_schema_requires_non_empty_command():
    command_schema = TERMINAL_SCHEMA["parameters"]["properties"]["command"]
    assert command_schema["type"] == "string"
    assert command_schema["minLength"] == 1


def test_terminal_rejects_none_and_empty_command_with_recovery_hint():
    none_result = json.loads(terminal_tool(None))
    assert none_result["status"] == "error"
    assert "non-empty string" in none_result["error"]
    assert "Re-emit" in none_result["error"]

    empty_result = json.loads(terminal_tool("   "))
    assert empty_result["status"] == "error"
    assert "command cannot be empty" in empty_result["error"]
    assert "search_files/read_file" in empty_result["error"]


def test_read_file_schema_requires_non_empty_path():
    path_schema = READ_FILE_SCHEMA["parameters"]["properties"]["path"]
    assert path_schema["type"] == "string"
    assert path_schema["minLength"] == 1


def test_read_file_handler_rejects_empty_path_with_recovery_hint():
    result = json.loads(_handle_read_file({"path": ""}, task_id="test"))
    assert "missing required field 'path'" in result["error"]
    assert "search_files" in result["error"]
