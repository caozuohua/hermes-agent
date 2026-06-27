"""``hermes tools`` subcommand parser.

Extracted from ``hermes_cli/main.py:main()`` (god-file Phase 2 follow-up).
Handler injected to avoid importing ``main``.
"""

from __future__ import annotations

from typing import Callable


def build_tools_parser(subparsers, *, cmd_tools: Callable) -> None:
    """Attach the ``tools`` subcommand to ``subparsers``."""
    tools_parser = subparsers.add_parser(
        "tools",
        help="Configure which tools are enabled per platform",
        description=(
            "Enable, disable, or list tools for CLI, Telegram, Discord, etc.\n\n"
            "Built-in toolsets use plain names (e.g. web, memory).\n"
            "MCP tools use server:tool notation (e.g. github:create_issue).\n\n"
            "Run 'hermes tools' with no subcommand for the interactive configuration UI."
        ),
    )
    tools_parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a summary of enabled tools per platform and exit",
    )
    tools_sub = tools_parser.add_subparsers(dest="tools_action")

    # hermes tools list [--platform cli]
    tools_list_p = tools_sub.add_parser(
        "list",
        help="Show all tools and their enabled/disabled status",
    )
    tools_list_p.add_argument(
        "--platform",
        default="cli",
        help="Platform to show (default: cli)",
    )

    # hermes tools budget-check [--platform cli] [--max-tools N]
    tools_budget_p = tools_sub.add_parser(
        "budget-check",
        help="Check the actual model-visible tool count",
        description=(
            "Resolve the configured toolsets, run tool availability checks, "
            "and count the final schemas sent to the model. This catches "
            "prompt-cost regressions from visible tools, not imported modules."
        ),
    )
    tools_budget_p.add_argument(
        "--platform",
        default="cli",
        help="Platform/profile surface to check (default: cli)",
    )
    tools_budget_p.add_argument(
        "--max-tools",
        type=int,
        default=1,
        help="Maximum allowed model-visible tools (default: 1 for Hermes-Lite)",
    )
    tools_budget_p.add_argument(
        "--json",
        action="store_true",
        help="Print the budget report as JSON",
    )

    # hermes tools disable <name...> [--platform cli]
    tools_disable_p = tools_sub.add_parser(
        "disable",
        help="Disable toolsets or MCP tools",
    )
    tools_disable_p.add_argument(
        "names",
        nargs="+",
        metavar="NAME",
        help="Toolset name (e.g. web) or MCP tool in server:tool form",
    )
    tools_disable_p.add_argument(
        "--platform",
        default="cli",
        help="Platform to apply to (default: cli)",
    )

    # hermes tools enable <name...> [--platform cli]
    tools_enable_p = tools_sub.add_parser(
        "enable",
        help="Enable toolsets or MCP tools",
    )
    tools_enable_p.add_argument(
        "names",
        nargs="+",
        metavar="NAME",
        help="Toolset name or MCP tool in server:tool form",
    )
    tools_enable_p.add_argument(
        "--platform",
        default="cli",
        help="Platform to apply to (default: cli)",
    )

    # hermes tools post-setup <key>
    tools_postsetup_p = tools_sub.add_parser(
        "post-setup",
        help="Run a provider's post-setup install hook (npm/pip/binary)",
        description=(
            "Run the install/bootstrap hook a tool backend declares — the\n"
            "same step `hermes tools` runs after you pick a provider that\n"
            "needs extra dependencies (browser Chromium, Camofox, cua-driver,\n"
            "KittenTTS/Piper, ddgs, Spotify, Langfuse, xAI). Stable,\n"
            "non-interactive target the dashboard spawns to drive backend\n"
            "setup. Keys: agent_browser, camofox, cua_driver, kittentts,\n"
            "piper, ddgs, spotify, langfuse, xai_grok."
        ),
    )
    tools_postsetup_p.add_argument(
        "post_setup_key",
        metavar="KEY",
        help="Post-setup hook key (e.g. agent_browser, camofox, kittentts)",
    )
    tools_parser.set_defaults(func=cmd_tools)
