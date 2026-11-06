"""Prompts submodule.

Prompts appear in the client UI as preset starters. Each prompt module
exposes a `register(mcp)` function; this file aggregates them. Both prompts
chain the tools and tell the model to keep to what the tools return.
"""

from __future__ import annotations

from crosswalk_mcp.prompts import review_release_changes, trace_relationships


def register_prompts(mcp) -> None:
    """Register all prompts with the MCP server."""
    review_release_changes.register(mcp)
    trace_relationships.register(mcp)


__all__ = ["register_prompts"]
