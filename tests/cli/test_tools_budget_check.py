from argparse import Namespace

import pytest

from hermes_cli import tools_config


def test_tools_budget_check_uses_actual_model_visible_report(monkeypatch, capsys):
    config = {
        "platform_toolsets": {"cli": ["search", "terminal", "file"]},
        "agent": {"disabled_toolsets": ["browser"]},
    }
    seen = {}

    def fake_report(**kwargs):
        seen.update(kwargs)
        return {
            "tool_count": 1,
            "tool_names": ["web_search"],
            "max_tools": 1,
            "within_budget": True,
            "over_budget_by": 0,
            "enabled_toolsets": kwargs["enabled_toolsets"],
            "disabled_toolsets": kwargs["disabled_toolsets"],
        }

    monkeypatch.setattr(tools_config, "load_config", lambda: config)
    monkeypatch.setattr(
        "model_tools.get_tool_surface_budget_report",
        fake_report,
    )

    rc = tools_config.tools_budget_check_command(
        Namespace(platform="cli", max_tools=1, json=False)
    )

    assert rc == 0
    assert seen == {
        "enabled_toolsets": ["file", "kanban", "search", "terminal"],
        "disabled_toolsets": ["browser"],
        "max_tools": 1,
    }
    out = capsys.readouterr().out
    assert "Tool surface budget: OK" in out
    assert "1/1 model-visible tools" in out
    assert "web_search" in out


def test_tools_budget_check_returns_failure_when_over_budget(monkeypatch, capsys):
    monkeypatch.setattr(
        tools_config,
        "load_config",
        lambda: {"platform_toolsets": {"cli": ["web"]}},
    )
    monkeypatch.setattr(
        "model_tools.get_tool_surface_budget_report",
        lambda **kwargs: {
            "tool_count": 2,
            "tool_names": ["web_extract", "web_search"],
            "max_tools": 1,
            "within_budget": False,
            "over_budget_by": 1,
            "enabled_toolsets": kwargs["enabled_toolsets"],
            "disabled_toolsets": kwargs["disabled_toolsets"],
        },
    )

    rc = tools_config.tools_budget_check_command(
        Namespace(platform="cli", max_tools=1, json=False)
    )

    assert rc == 1
    assert "Tool surface budget: OVER" in capsys.readouterr().out


def test_tools_budget_check_json_output(monkeypatch, capsys):
    monkeypatch.setattr(
        tools_config,
        "load_config",
        lambda: {"platform_toolsets": {"cli": ["search"]}},
    )
    monkeypatch.setattr(
        "model_tools.get_tool_surface_budget_report",
        lambda **kwargs: {
            "tool_count": 0,
            "tool_names": [],
            "max_tools": 1,
            "within_budget": True,
            "over_budget_by": 0,
            "enabled_toolsets": kwargs["enabled_toolsets"],
            "disabled_toolsets": kwargs["disabled_toolsets"],
        },
    )

    rc = tools_config.tools_budget_check_command(
        Namespace(platform="cli", max_tools=1, json=True)
    )

    assert rc == 0
    assert '"tool_count": 0' in capsys.readouterr().out
