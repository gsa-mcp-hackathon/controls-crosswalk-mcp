"""Resources a client can read without a tool call."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from crosswalk_mcp.tools.data_status import data_status


def register(mcp: FastMCP) -> None:
    @mcp.resource("crosswalk://data-status", mime_type="application/json")
    def data_status_resource() -> str:
        """Datasets, releases, snapshot hash, and pinned sources, as JSON."""
        return json.dumps(data_status(), indent=2)
