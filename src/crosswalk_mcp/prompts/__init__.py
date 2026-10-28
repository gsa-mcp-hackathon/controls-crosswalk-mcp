"""Prompts submodule.

Prompts appear in the client UI as preset starters. Each prompt module
exposes a `register(mcp)` function; this file aggregates them. Prompts are
added once the crosswalk tools exist, since they chain those tools.
"""

from __future__ import annotations


def register_prompts(mcp) -> None:
    """Register all prompts with the MCP server."""


__all__ = ["register_prompts"]
