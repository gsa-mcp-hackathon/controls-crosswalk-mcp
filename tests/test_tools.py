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
    assert names == {
        "controls_get_control",
        "controls_search",
        "controls_get_baseline",
        "controls_baseline_membership",
        "controls_diff_releases",
        "controls_get_csf_element",
        "controls_get_ksi",
        "controls_crosswalk",
        "controls_data_status",
    }


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
    assert [d["release"] for d in result["datasets"]] == [
        "5.2.0",
        "5.1.1",
        "2.0",
        "2026.01.01.01",
    ]
    assert result["datasets"][3] == {
        "dataset": "FedRAMP Consolidated Rules",
        "release": "2026.01.01.01",
        "last_updated": "2026-01-01",
        "source_key": "fedramp_rules",
        "ksi_themes": 2,
        "ksi_indicators": 3,
        "ksi_control_links": 5,
        "definitions": 1,
        "controls_with_guidance": 3,
    }
    assert result["datasets"][0]["controls_and_enhancements"] == 5
    assert result["datasets"][2] == {
        "dataset": "CSF 2.0",
        "release": "2.0",
        "version_as_published": "Version 2.0",
        "source_key": "csf_2_0_0",
        "active": {"function": 2, "category": 1, "subcategory": 2},
        "legacy_identifiers": 2,
    }
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


async def test_search_ranks_and_snippets(tiny_store):
    result = await call("controls_search", query="account managers")
    assert result["match_mode"] == "all_words"
    assert result["total"] == 1
    hit = result["results"][0]
    assert hit["id"] == "AC-2"
    assert "[account] [managers]" in hit["snippet"].lower()
    assert hit["baselines"] == ["low", "moderate", "high"]
    assert hit["score"] > 0
    assert result["provenance"]["release"] == "5.2.0"


async def test_search_falls_back_to_any_word(tiny_store):
    result = await call("controls_search", query="audit zebra")
    assert result["match_mode"] == "any_word"
    assert [h["id"] for h in result["results"]] == ["AU-6"]
    assert result["notes"] and "at least one word" in result["notes"][0]


async def test_search_filters_and_withdrawn(tiny_store):
    assert (await call("controls_search", query="withdrawn"))["total"] == 0
    result = await call("controls_search", query="withdrawn", include_withdrawn=True)
    assert {h["id"] for h in result["results"]} == {"AC-2(10)", "AC-13"}
    result = await call("controls_search", query="audit", baseline="privacy")
    assert [h["id"] for h in result["results"]] == ["AU-6"]
    result = await call("controls_search", query="audit", family="ac")
    assert result["total"] == 0 and result["filters"]["family"] == "AC"
    with pytest.raises(ToolError, match="not an SP 800-53 family"):
        await call("controls_search", query="audit", family="ZZ")


async def test_search_rejects_operator_only_query(tiny_store):
    with pytest.raises(ToolError, match="no searchable words"):
        await call("controls_search", query='" * "')


async def test_search_pagination(tiny_store):
    result = await call(
        "controls_search",
        query="withdrawn",
        include_withdrawn=True,
        pagination={"limit": 1, "offset": 0},
    )
    assert result["count"] == 1 and result["total"] == 2
    assert result["has_more"] is True and result["next_offset"] == 1


async def test_get_baseline(tiny_store):
    result = await call("controls_get_baseline", baseline="moderate")
    assert result["baseline"]["member_count"] == 2
    assert result["baseline"]["catalog_version"] == "9.9.9"
    assert [m["id"] for m in result["members"]] == ["AC-2", "AU-6"]
    assert result["members"][0]["oscal_id"] == "ac-2"
    assert result["relationship"] == "direct"
    assert result["notes"] == []
    assert result["provenance"]["source"]["key"] == "baseline_moderate"
    assert len(result["provenance"]["source"]["pin"]) == 40

    result = await call("controls_get_baseline", baseline="moderate", family="AU")
    assert [m["id"] for m in result["members"]] == ["AU-6"]

    result = await call("controls_get_baseline", baseline="high")
    assert "different release" in result["notes"][0]


async def test_baseline_membership(tiny_store):
    result = await call(
        "controls_baseline_membership", control_ids=["ac-02", "AC-13", "AC-99"]
    )
    by_id = {c["id"]: c for c in result["controls"]}
    assert by_id["AC-2"]["baselines"] == ["low", "moderate", "high"]
    assert by_id["AC-2"]["title"] == "ACCOUNT MANAGEMENT"
    assert by_id["AC-13"] == {
        "id": "AC-13",
        "found": True,
        "title": "SUPERVISION AND REVIEW",
        "withdrawn": True,
        "baselines": [],
    }
    assert by_id["AC-99"]["found"] is False
    assert "AC-99" in result["notes"][0]
    assert result["relationship"] == "direct"
    assert [s["key"] for s in result["provenance"]["sources"]] == [
        "baseline_low",
        "baseline_moderate",
        "baseline_high",
        "baseline_privacy",
    ]
    with pytest.raises(ToolError, match="more than once"):
        await call("controls_baseline_membership", control_ids=["AC-2", "ac-02"])


async def test_diff_releases_catalog_and_family(tiny_store):
    result = await call("controls_diff_releases")
    assert result["from_release"] == "5.1.1" and result["to_release"] == "5.2.0"
    assert result["summary"] == {
        "added": 1,
        "removed": 0,
        "changed": 1,
        "unchanged": 3,
        "changed_by_section": {
            "statement": 1,
            "discussion": 1,
            "parameters": 1,
            "relations": 1,
        },
    }
    assert result["added"] == [
        {
            "id": "AC-25",
            "title": "REFERENCE MONITOR",
            "parent_id": None,
            "withdrawn": False,
        }
    ]
    assert result["changed"]["items"][0]["id"] == "AC-2"
    assert result["changed"]["has_more"] is False
    assert result["provenance"]["from"]["source"]["key"] == "sp800_53_5_1_1"
    assert result["provenance"]["to"]["source"]["key"] == "sp800_53_5_2_0"

    result = await call("controls_diff_releases", family="au")
    assert result["scope"]["family"] == "AU"
    assert result["summary"]["added"] == 0 and result["summary"]["changed"] == 0
    assert result["summary"]["unchanged"] == 1

    result = await call("controls_diff_releases", pagination={"limit": 1, "offset": 1})
    assert result["changed"]["count"] == 0 and result["changed"]["total"] == 1


async def test_diff_releases_one_control(tiny_store):
    result = await call("controls_diff_releases", control_id="ac-02")
    assert result["status"] == "changed"
    assert result["changed_sections"] == [
        "statement",
        "discussion",
        "parameters",
        "relations",
    ]
    changes = result["changes"]
    assert changes["statement"]["changed"] == [
        {
            "id": "CST-AC-02-a",
            "fields": {
                "text": {
                    "before": "Define account types;",
                    "after": "Define and document account types;",
                }
            },
        }
    ]
    assert changes["discussion"]["changes"] == [
        {
            "before": "First & second.\n\nThird.",
            "after": "First & second.\n\nThird.\n\nFourth.",
        }
    ]
    assert changes["parameters"]["changed"][0]["fields"]["label"] == {
        "before": "prerequisites",
        "after": "account prerequisites",
    }
    assert changes["relations"] == {"related": {"added": ["AC-25"], "removed": []}}
    assert "controls_get_control" in result["notes"][0]
    citations = result["provenance"]["citations"]
    assert citations["from"]["text"].startswith("NIST SP 800-53 Rev. 5 release 5.1.1")
    assert citations["to"]["url"].endswith("element=AC-02")

    result = await call("controls_diff_releases", control_id="AC-25")
    assert result["status"] == "added" and result["changes"] == {}
    assert list(result["provenance"]["citations"]) == ["to"]

    result = await call("controls_diff_releases", control_id="AU-6")
    assert result["status"] == "unchanged"
    assert "same in 5.1.1 and 5.2.0" in result["notes"][0]


async def test_diff_releases_errors(tiny_store):
    with pytest.raises(ToolError, match="not both"):
        await call("controls_diff_releases", control_id="AC-2", family="AC")
    with pytest.raises(ToolError, match="both 5.2.0"):
        await call("controls_diff_releases", from_release="5.2.0")
    with pytest.raises(ToolError, match="Swap them"):
        await call("controls_diff_releases", from_release="5.2.0", to_release="5.1.1")
    with pytest.raises(ToolError, match="controls_search"):
        await call("controls_diff_releases", control_id="AC-99")
    with pytest.raises(ToolError, match="not an SP 800-53 family"):
        await call("controls_diff_releases", family="ZZ")
