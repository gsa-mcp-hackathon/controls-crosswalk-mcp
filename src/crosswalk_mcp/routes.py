"""Custom HTTP routes for the MCP server.

These are only active when the server runs over HTTP (streamable-http). They
sit alongside the `/mcp` endpoint on the same app.

The `/health` route matters for cloud deploys: cloud.gov, IBM Code Engine, and
Databricks Apps all use an HTTP health check to decide the app started
correctly. Keep it fast. It only checks that the store file exists, because
without the store every data tool fails.
"""

from __future__ import annotations

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from crosswalk_mcp import __version__
from crosswalk_mcp.tools.common import store_ready


def register_routes(mcp: FastMCP) -> None:
    """Register custom HTTP routes with the server."""

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> JSONResponse:
        service = "controls-crosswalk-mcp"
        if not store_ready():
            # 503 tells a platform health check the app cannot serve yet.
            # https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/503
            return JSONResponse(
                {
                    "status": "unavailable",
                    "service": service,
                    "store": "missing",
                    "detail": "Build the store: python -m crosswalk_mcp.store build",
                },
                status_code=503,
            )
        return JSONResponse({"status": "healthy", "service": service, "store": "ready"})

    @mcp.custom_route("/version", methods=["GET"])
    async def version(request: Request) -> JSONResponse:
        return JSONResponse({"version": __version__})
