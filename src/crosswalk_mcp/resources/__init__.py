"""Resources submodule.

Resources are addressable by URI and need no tool call. Each resource module
exposes a `register(mcp)` function; this file aggregates them.

    crosswalk://data-status   datasets, releases, snapshot hash, sources
    crosswalk://families      SP 800-53 families per release
    crosswalk://csf-outline   CSF 2.0 functions and categories
    crosswalk://ksi-themes    FedRAMP KSI themes and indicators
"""

from __future__ import annotations

from crosswalk_mcp.resources import about, catalogs


def register_resources(mcp) -> None:
    """Register all resources with the MCP server."""
    about.register(mcp)
    catalogs.register(mcp)


__all__ = ["register_resources"]
