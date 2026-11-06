"""Tests for the prompts and the reference resources."""

from __future__ import annotations

import json

from fastmcp import Client

from crosswalk_mcp.app import mcp


async def test_prompts_are_listed_with_arguments():
    async with Client(mcp) as client:
        prompts = {p.name: p for p in await client.list_prompts()}
    assert set(prompts) == {"review_release_changes", "trace_relationships"}
    review = prompts["review_release_changes"]
    assert [a.name for a in review.arguments] == [
        "scope",
        "from_release",
        "to_release",
    ]
    assert all(not a.required for a in review.arguments)
    trace = prompts["trace_relationships"]
    assert [(a.name, a.required) for a in trace.arguments] == [("identifier", True)]


async def test_review_release_changes_prompt_names_the_tools():
    async with Client(mcp) as client:
        whole = await client.get_prompt("review_release_changes")
        family = await client.get_prompt(
            "review_release_changes",
            {"scope": "SI", "from_release": "5.1.1", "to_release": "5.2.0"},
        )
    text = whole.messages[0].content.text
    assert whole.messages[0].role == "user"
    assert "for the whole catalog" in text
    assert "controls_diff_releases" in text
    assert "controls_baseline_membership" in text
    assert "Do not say whether any organization meets a control" in text
    assert "for SI." in family.messages[0].content.text


async def test_trace_relationships_prompt_names_the_tools():
    async with Client(mcp) as client:
        result = await client.get_prompt(
            "trace_relationships", {"identifier": " PR.AA-01 "}
        )
    text = result.messages[0].content.text
    assert "start from PR.AA-01." in text
    for tool in (
        "controls_get_control",
        "controls_get_csf_element",
        "controls_get_ksi",
        "controls_crosswalk",
    ):
        assert tool in text
    assert "derived" in text


async def test_reference_resources(tiny_store):
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
        assert uris == {
            "crosswalk://data-status",
            "crosswalk://families",
            "crosswalk://csf-outline",
            "crosswalk://ksi-themes",
        }
        families = json.loads(
            (await client.read_resource("crosswalk://families"))[0].text
        )
        outline = json.loads(
            (await client.read_resource("crosswalk://csf-outline"))[0].text
        )
        themes = json.loads(
            (await client.read_resource("crosswalk://ksi-themes"))[0].text
        )

    assert families["default_release"] == "5.2.0"
    assert families["families_by_release"]["5.2.0"] == [
        {"id": "AC", "title": "ACCESS CONTROL", "active_controls": 2},
        {"id": "AU", "title": "AUDIT AND ACCOUNTABILITY", "active_controls": 1},
    ]
    assert len(families["provenance"]["snapshot_hash"]) == 64

    assert [f["id"] for f in outline["functions"]] == ["GV", "ID"]
    assert outline["functions"][0]["categories"] == [
        {"id": "GV.OC", "title": "Organizational Context", "text": "Context."}
    ]
    assert outline["functions"][1]["categories"] == []  # ID.BE is legacy

    assert [t["id"] for t in themes["themes"]] == ["KSI-CED", "KSI-CMT"]
    assert themes["themes"][0]["indicators"] == [
        {"id": "KSI-CED-RAT", "name": "Reviewing All Training"},
        {"id": "KSI-CED-VAR", "name": "Varies"},
    ]
