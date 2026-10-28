"""Tools submodule, one tool per file.

Each tool module exposes a `register(mcp)` function that attaches its
`@mcp.tool` decorated function to the server. This file aggregates them into
`register_tools(mcp)`, which app.py calls. Shared helpers live in common.py.
"""

from __future__ import annotations

from crosswalk_mcp.tools import data_status, get_control


def register_tools(mcp) -> None:
    """Register all tools with the MCP server."""
    get_control.register(mcp)
    data_status.register(mcp)


__all__ = ["register_tools"]
