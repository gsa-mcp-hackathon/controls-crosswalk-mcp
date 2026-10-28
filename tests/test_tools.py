"""Tool tests, run through an in-memory MCP client against the tiny store."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from crosswalk_mcp.app import mcp
from crosswalk_mcp.tools import common


async def call(name: str, **args) -> dict:
    async with Client(mcp) as client:
        result = await client.call_tool(name, args)
    return result.data


async def test_tools_are_listed():
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == {"controls_get_control", "controls_data_status"}


async def test_get_control_returns_record_and_provenance(tiny_store):
    result = await call("controls_get_control", control_id="ac-02")
    control = result["control"]
    assert control["id"] == "AC-2"
    assert control["title"] == "ACCOUNT MANAGEMENT"
    assert control["statement"][0]["items"][0]["label"] == "a"
    assert control["enhancements"][0]["id"] == "AC-2(10)"
    assert result["notes"] == []

    provenance = result["provenance"]
    assert provenance["release"] == "5.2.0"
    assert len(provenance["snapshot_hash"]) == 64
    assert provenance["source"]["key"] == "sp800_53_5_2_0"
    assert provenance["source"]["url"].startswith("https://csrc.nist.gov/")
    assert provenance["citation"]["url"].endswith("SP_800_53_TEST/home?element=AC-02")
    assert "AC-02 ACCOUNT MANAGEMENT" in provenance["citation"]["text"]


async def test_get_control_release_and_sections(tiny_store):
    result = await call(
        "controls_get_control",
        control_id="AC-2",
        release="5.1.1",
        sections=["statement", "parameters"],
    )
    control = result["control"]
    assert result["provenance"]["release"] == "5.1.1"
    assert "statement" in control and "parameters" in control
    assert "discussion" not in control
    assert "related" not in control
    assert "enhancements" not in control
    # Core fields stay no matter which sections were asked for.
    assert control["family_title"] == "ACCESS CONTROL"
    assert control["cprt_baselines"] == ["low", "moderate"]


async def test_get_control_withdrawn_note(tiny_store):
    result = await call("controls_get_control", control_id="AC-13")
    assert result["control"]["withdrawn"] is True
    assert result["notes"] == [
        "AC-13 is withdrawn in release 5.2.0: Incorporated into AC-2, AU-6."
    ]


async def test_get_control_errors_are_actionable(tiny_store):
    with pytest.raises(ToolError, match="not an SP 800-53 control id"):
        await call("controls_get_control", control_id="PR.AA-01")
    with pytest.raises(ToolError, match="controls_search"):
        await call("controls_get_control", control_id="AC-99")


async def test_missing_store_is_reported(tmp_path):
    common.configure_store(tmp_path / "nope.sqlite")
    try:
        with pytest.raises(ToolError, match="operator must build it"):
            await call("controls_get_control", control_id="AC-2")
    finally:
        common.configure_store(None)


async def test_data_status(tiny_store):
    result = await call("controls_data_status")
    assert [d["release"] for d in result["datasets"]] == ["5.2.0", "5.1.1"]
    assert result["datasets"][0]["controls_and_enhancements"] == 4
    assert len(result["sources"]) == 8
    pinned = [s for s in result["sources"] if s["pin"]]
    assert all(len(s["pin"]) == 40 for s in pinned)
    assert all(s["sha256"] for s in result["sources"])
    assert "never states that a requirement is satisfied" in result["scope"]
    assert len(result["provenance"]["snapshot_hash"]) == 64


async def test_data_status_resource_matches_tool(tiny_store):
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
        assert "crosswalk://data-status" in uris
        contents = await client.read_resource("crosswalk://data-status")
    payload = json.loads(contents[0].text)
    tool_result = await call("controls_data_status")
    assert payload["provenance"] == tool_result["provenance"]
