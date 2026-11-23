"""Tests for controls_crosswalk and the FedRAMP section of get_control.

The tiny fixtures link GV.OC-01 to the AC and AU families, GV.OC to PM,
KSI-CED-RAT to AC-2, AC-2(10), AU-6, and PL-4, and KSI-CMT-LMC to AU-6.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from crosswalk_mcp import store
from crosswalk_mcp.tools import common
from tests.test_tools import call


def _ids(hits: list[dict]) -> list[str]:
    return [hit["id"] for hit in hits]


async def test_control_to_ksi_is_direct(tiny_store):
    result = await call("controls_crosswalk", source_id="au-06", to_framework="ksi")
    assert result["source"] == {
        "framework": "sp800_53",
        "id": "AU-6",
        "title": "AUDIT RECORD REVIEW",
        "family": "AU",
        "withdrawn": False,
    }
    assert _ids(result["direct"]) == ["KSI-CED-RAT", "KSI-CMT-LMC"]
    hit = result["direct"][0]
    assert hit["relationship"] == "direct"
    assert hit["hops"] == 1
    assert hit["path"] == ["AU-6", "KSI-CED-RAT"]
    assert hit["links"] == [
        {
            "from": "KSI-CED-RAT",
            "to": "AU-6",
            "type": "related_control",
            "publisher": "FedRAMP",
            "level": "control",
            "catalog_release": "unspecified",
            "direction": "reverse",
            "source": "fedramp_rules",
        }
    ]
    assert hit["citation"]["json_path"] == "KSI.CED.indicators.KSI-CED-RAT"
    assert result["derived"]["total"] == 0
    assert [s["key"] for s in result["provenance"]["sources"]] == ["fedramp_rules"]


async def test_control_to_csf_is_derived_through_family(tiny_store):
    result = await call("controls_crosswalk", source_id="AC-2", to_framework="csf")
    assert result["direct"] == []
    derived = result["derived"]
    assert derived["total"] == 1
    hit = derived["items"][0]
    assert hit["id"] == "GV.OC-01"
    assert hit["relationship"] == "derived"
    assert hit["hops"] == 1
    assert hit["path"] == ["AC-2", "AC", "GV.OC-01"]
    assert [link["type"] for link in hit["links"]] == [
        "family_membership",
        "informative_reference",
    ]
    assert hit["links"][1]["direction"] == "reverse"
    assert hit["links"][1]["catalog_release"] == "5.1.1"
    assert hit["citation"]["url"].endswith("element=GV.OC-01")
    assert any("name the AC family" in note for note in result["notes"])
    assert any("Derived hits compose" in note for note in result["notes"])


async def test_csf_to_controls_lists_families(tiny_store):
    result = await call(
        "controls_crosswalk", source_id="gv.oc-01", to_framework="sp800_53"
    )
    assert result["source"]["kind"] == "subcategory"
    assert _ids(result["direct"]) == ["AC", "AU"]
    hit = result["direct"][0]
    assert hit["kind"] == "family"
    assert hit["title"] == "ACCESS CONTROL"
    assert hit["links"][0]["direction"] == "as_published"
    assert result["derived"]["total"] == 0
    assert any("family level" in note for note in result["notes"])
    # The family hit cites the CSF element, where NIST publishes the link.
    assert hit["citation"]["url"].endswith("element=GV.OC-01")
    assert [s["key"] for s in result["provenance"]["sources"]] == ["csf_2_0_0"]


async def test_no_hits_still_names_the_source_searched(tiny_store):
    """An empty answer must say where the server looked."""
    result = await call(
        "controls_crosswalk", source_id="KSI-CED-VAR", to_framework="sp800_53"
    )
    assert result["direct"] == []
    assert result["derived"]["total"] == 0
    assert any("No published link" in note for note in result["notes"])
    assert [s["key"] for s in result["provenance"]["sources"]] == ["fedramp_rules"]


async def test_csf_to_ksi_composes_two_hops(tiny_store):
    result = await call("controls_crosswalk", source_id="GV.OC-01", to_framework="ksi")
    assert result["direct"] == []
    items = result["derived"]["items"]
    assert _ids(items) == ["KSI-CED-RAT", "KSI-CMT-LMC"]
    rat = items[0]
    assert rat["hops"] == 2
    assert rat["path"] == ["GV.OC-01", "AC", "AC-2", "KSI-CED-RAT"]
    assert [link["type"] for link in rat["links"]] == [
        "informative_reference",
        "family_membership",
        "related_control",
    ]
    assert rat["via"] == {
        "families": ["AC", "AU"],
        "controls": ["AC-2", "AC-2(10)", "AU-6"],
    }
    assert items[1]["via"] == {"families": ["AU"], "controls": ["AU-6"]}
    assert sorted(s["key"] for s in result["provenance"]["sources"]) == [
        "csf_2_0_0",
        "fedramp_rules",
        "sp800_53_5_2_0",
    ]

    result = await call(
        "controls_crosswalk", source_id="GV.OC-01", to_framework="ksi", max_hops=1
    )
    assert result["derived"]["total"] == 0
    assert "Set max_hops to 2" in result["notes"][0]


async def test_ksi_to_controls_is_direct(tiny_store):
    result = await call(
        "controls_crosswalk", source_id="ksi-ced-rat", to_framework="sp800_53"
    )
    assert _ids(result["direct"]) == ["AC-2", "AC-2(10)", "AU-6", "PL-4"]
    assert result["direct"][0]["citation"]["url"].endswith("element=AC-02")
    assert result["direct"][1]["withdrawn"] is True
    assert result["direct"][3] == {
        "framework": "sp800_53",
        "id": "PL-4",
        "title": None,
        "withdrawn": None,
        "citation": None,
        "relationship": "direct",
        "hops": 1,
        "path": ["KSI-CED-RAT", "PL-4"],
        "links": result["direct"][3]["links"],
    }
    assert result["direct"][3]["links"][0]["direction"] == "as_published"
    assert any("Not in SP 800-53 release 5.2.0: PL-4" in n for n in result["notes"])


async def test_ksi_to_csf_composes_two_hops(tiny_store):
    result = await call(
        "controls_crosswalk", source_id="KSI-CED-RAT", to_framework="csf"
    )
    items = result["derived"]["items"]
    assert _ids(items) == ["GV.OC-01"]
    hit = items[0]
    assert hit["path"] == ["KSI-CED-RAT", "AC-2", "AC", "GV.OC-01"]
    assert hit["via"] == {
        "families": ["AC", "AU"],
        "controls": ["AC-2", "AC-2(10)", "AU-6"],
    }
    assert hit["links"][0]["direction"] == "as_published"
    assert hit["links"][2]["direction"] == "reverse"

    result = await call(
        "controls_crosswalk",
        source_id="KSI-CED-RAT",
        to_framework="csf",
        pagination={"limit": 1, "offset": 1},
    )
    assert result["derived"]["total"] == 1
    assert result["derived"]["items"] == []
    assert result["derived"]["has_more"] is False


async def test_no_published_link_is_a_distinct_result(tiny_store):
    result = await call("controls_crosswalk", source_id="GV.OC-02", to_framework="ksi")
    assert result["direct"] == []
    assert result["derived"]["total"] == 0
    assert "gap in the published mappings" in result["notes"][0]


async def test_crosswalk_errors(tiny_store):
    with pytest.raises(ToolError, match="already in sp800_53"):
        await call("controls_crosswalk", source_id="AC-2", to_framework="sp800_53")
    with pytest.raises(ToolError, match="two letter code"):
        await call("controls_crosswalk", source_id="AC", to_framework="csf")
    with pytest.raises(ToolError, match="not an identifier this tool accepts"):
        await call("controls_crosswalk", source_id="what", to_framework="csf")
    with pytest.raises(ToolError, match="SP 800-171"):
        await call("controls_crosswalk", source_id="03.01.01", to_framework="csf")
    with pytest.raises(ToolError, match="two letter code"):
        await call("controls_crosswalk", source_id="GV", to_framework="ksi")
    with pytest.raises(ToolError, match="KSI theme"):
        await call("controls_crosswalk", source_id="KSI-CED", to_framework="csf")
    with pytest.raises(ToolError, match="not in SP 800-53 release 5.2.0"):
        await call("controls_crosswalk", source_id="AC-99", to_framework="csf")
    with pytest.raises(ToolError, match="controls_get_csf_element"):
        await call("controls_crosswalk", source_id="PR.AA-01", to_framework="ksi")
    with pytest.raises(ToolError, match="controls_get_ksi"):
        await call("controls_crosswalk", source_id="KSI-CED-NO", to_framework="csf")


async def test_legacy_csf_source_is_noted(tiny_store):
    result = await call("controls_crosswalk", source_id="ID.BE-02", to_framework="ksi")
    assert result["source"]["status"] == "legacy"
    assert "retired CSF 1.1 identifier" in result["notes"][0]
    assert result["derived"]["total"] == 0


async def test_get_control_fedramp_section(tiny_store):
    result = await call("controls_get_control", control_id="AC-2")
    control = result["control"]
    assert control["fedramp_ksis"] == [
        {"id": "KSI-CED-RAT", "name": "Reviewing All Training", "theme_id": "KSI-CED"}
    ]
    assert control["fedramp_guidance"] == [
        {
            "class": None,
            "guidance": ["Follow the guide."],
            "parameters": [],
            "updated": [],
        }
    ]
    result = await call(
        "controls_get_control", control_id="AC-2(10)", sections=["fedramp"]
    )
    control = result["control"]
    assert "statement" not in control
    assert control["fedramp_guidance"][0]["class"] == "c"
    assert control["fedramp_guidance"][0]["parameters"][0]["value"] == "daily"
    result = await call(
        "controls_get_control", control_id="AC-25", sections=["statement"]
    )
    assert "fedramp_ksis" not in result["control"]
    assert "fedramp" not in result["provenance"]


async def test_get_control_cites_fedramp_for_fedramp_content(tiny_store):
    """FedRAMP guidance and KSI links are FedRAMP's, so the result has to
    name the FedRAMP file, not only the NIST one."""
    result = await call("controls_get_control", control_id="AC-2")
    provenance = result["provenance"]
    assert provenance["source"]["key"] == "sp800_53_5_2_0"
    fedramp = provenance["fedramp"]
    assert fedramp["source"]["key"] == "fedramp_rules"
    assert fedramp["source"]["publisher"] == "FedRAMP"
    assert fedramp["document"]["version"] == "2026.01.01.01"
    assert fedramp["citation"]["url"] == fedramp["source"]["url"]
    assert fedramp["citation"]["json_paths"] == [
        "KSI.CED.indicators.KSI-CED-RAT",
        "CTL.AC.AC-02",
    ]

    result = await call(
        "controls_get_control", control_id="AC-2(10)", sections=["fedramp"]
    )
    paths = result["provenance"]["fedramp"]["citation"]["json_paths"]
    assert paths[-1] == "CTL.AC.AC-02-10"


@pytest.mark.skipif(
    not (Path("data") / store.DB_NAME).exists()
    or not (Path("data") / "raw" / "fedramp_consolidated_rules.json").exists(),
    reason="real store or FedRAMP file not present",
)
def test_real_fedramp_guidance_paths_exist_in_the_file():
    """Every CTL path the control tool cites must be a real key in the
    pinned FedRAMP file."""
    import json

    from crosswalk_mcp.tools.get_control import _ctl_key

    payload = json.loads(
        (Path("data") / "raw" / "fedramp_consolidated_rules.json").read_text()
    )
    s = store.open_store(Path("data") / store.DB_NAME)
    rows = s.conn.execute(
        "SELECT DISTINCT control_id FROM fedramp_control_guidance"
    ).fetchall()
    assert rows
    for row in rows:
        control_id = row["control_id"]
        family = control_id.split("-")[0]
        assert _ctl_key(control_id) in payload["CTL"][family], control_id
    s.close()


REAL_STORE = Path("data") / store.DB_NAME


@pytest.mark.skipif(not REAL_STORE.exists(), reason="real store not built")
async def test_real_ksi_with_no_controls_names_its_source():
    """KSI-PIY-RES lists no related controls. The result still cites FedRAMP."""
    common.configure_store(REAL_STORE)
    try:
        result = await call(
            "controls_crosswalk", source_id="KSI-PIY-RES", to_framework="sp800_53"
        )
    finally:
        common.configure_store(None)
    assert result["direct"] == []
    assert [s["key"] for s in result["provenance"]["sources"]] == ["fedramp_rules"]


@pytest.mark.skipif(not REAL_STORE.exists(), reason="real store not built")
def test_real_store_crosswalk_facts():
    s = store.open_store(REAL_STORE)
    # PR.AA-01 references the IA family; every IA control that a KSI names
    # must therefore show up on the CSF to KSI path.
    ia_controls = [c["id"] for c in s.controls_in_family("IA", "5.2.0")]
    ksis = {row["id"] for row in s.ksis_for_controls(ia_controls)}
    assert {"KSI-IAM-AAM", "KSI-IAM-SNU"} <= ksis
    assert {r["id"] for r in s.csf_elements_for_families(["IA"])} >= {
        "PR.AA-01",
        "PR.AA-03",
    }
    assert s.fedramp_guidance("AC-20")[0]["guidance"][0].startswith(
        "The interrelated controls"
    )
    assert [g["class"] for g in s.fedramp_guidance("SA-9(5)")] == ["c", "d"]
    s.close()
