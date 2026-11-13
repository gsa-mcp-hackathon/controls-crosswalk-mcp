"""Expose the MCP server's tools to a LangChain agent.

The template's mcp-eval skill uses langchain-mcp-adapters for this, but that
package pins the mcp library below 2.0 while FastMCP 4 needs 2.x. This
module does the same job with the FastMCP client that the server already
depends on: it launches the server over stdio, lists its tools, and wraps
each one as a LangChain StructuredTool whose argument schema is the tool's
own JSON schema. Results are returned to the agent as JSON text.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError
from langchain_core.tools import StructuredTool

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def stdio_transport() -> StdioTransport:
    """Launch the server the way a local client would: `uv run crosswalk-mcp`
    from the repo root, so it finds data/crosswalk.sqlite."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("USAI_")}
    return StdioTransport(
        command="uv",
        args=["run", "--no-sync", "crosswalk-mcp"],
        cwd=str(REPO_ROOT),
        env=env,
        keep_alive=True,
    )


class McpToolbox:
    """A connected FastMCP client and the LangChain tools built from it.

    Use as an async context manager so the server process is closed when the
    run ends:

        async with McpToolbox() as toolbox:
            agent = create_agent(model, toolbox.tools, ...)
    """

    def __init__(self, client: Client | None = None):
        self.client = client or Client(stdio_transport())
        self.tools: list[StructuredTool] = []

    async def __aenter__(self) -> McpToolbox:
        await self.client.__aenter__()
        self.tools = [self._wrap(tool) for tool in await self.client.list_tools()]
        return self

    async def __aexit__(self, *exc) -> None:
        await self.client.__aexit__(*exc)

    def _wrap(self, tool) -> StructuredTool:
        name = tool.name

        async def run(**kwargs: Any) -> str:
            try:
                result = await self.client.call_tool(name, kwargs)
            except ToolError as exc:
                # The server's errors are written for the model. Hand them
                # over as text so the agent can change course.
                return json.dumps({"error": str(exc)})
            return json.dumps(result.data, default=str)

        return StructuredTool.from_function(
            coroutine=run,
            name=name,
            description=tool.description or name,
            args_schema=tool.input_schema,
        )
