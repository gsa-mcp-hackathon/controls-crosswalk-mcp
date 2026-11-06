"""Tools submodule, one tool per file.

Each tool module exposes a `register(mcp)` function that attaches its
`@mcp.tool` decorated function to the server. This file aggregates them into
`register_tools(mcp)`, which app.py calls. Shared helpers live in common.py.
"""

from __future__ import annotations

from crosswalk_mcp.tools import (
    baselines,
    data_status,
    diff_releases,
    get_control,
    get_csf_element,
    get_ksi,
    search,
)


def register_tools(mcp) -> None:
    """Register all tools with the MCP server."""
    get_control.register(mcp)
    search.register(mcp)
    baselines.register(mcp)
    diff_releases.register(mcp)
    get_csf_element.register(mcp)
    get_ksi.register(mcp)
    data_status.register(mcp)


__all__ = ["register_tools"]
