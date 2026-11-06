"""Smoke tests for the MCP server.

These verify the server imports and every submodule registers without error.
Add functional tests for your own tools as you build them.
"""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from crosswalk_mcp.app import mcp
from crosswalk_mcp.config import settings


def test_server_is_importable():
    assert mcp is not None


def test_server_has_name():
    assert mcp.name == "Controls Crosswalk MCP"


def test_default_transport_is_stdio():
    """Guard against accidentally shipping with a non-stdio default."""
    assert settings.mcp_transport == "stdio"


def test_tools_register_without_error():
    from crosswalk_mcp.tools import register_tools

    register_tools(FastMCP("test"))  # must not raise


def test_prompts_register_without_error():
    from crosswalk_mcp.prompts import register_prompts

    register_prompts(FastMCP("test"))  # must not raise


def test_resources_register_without_error():
    from crosswalk_mcp.resources import register_resources

    register_resources(FastMCP("test"))  # must not raise


def test_routes_register_without_error():
    from crosswalk_mcp.routes import register_routes

    register_routes(FastMCP("test"))  # must not raise


@pytest.mark.asyncio
async def test_tools_are_discoverable():
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert {
        "controls_get_control",
        "controls_search",
        "controls_get_baseline",
        "controls_baseline_membership",
        "controls_diff_releases",
        "controls_get_csf_element",
        "controls_get_ksi",
        "controls_data_status",
    } <= tool_names
