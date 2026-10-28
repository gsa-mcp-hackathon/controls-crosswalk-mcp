"""Resources submodule.

Resources are addressable by URI and need no tool call. Each resource module
exposes a `register(mcp)` function; this file aggregates them.
"""

from __future__ import annotations

from crosswalk_mcp.resources import about


def register_resources(mcp) -> None:
    """Register all resources with the MCP server."""
    about.register(mcp)


__all__ = ["register_resources"]
