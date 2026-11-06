"""Tests for the FedRAMP rules loader, its store tables, and the KSI tool.

The loader and store tests use the tiny rules file in fixtures.py. A final
test checks the real store, when it is built, against facts verified by
hand in the published file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from crosswalk_mcp import store
from crosswalk_mcp.loaders import fedramp
from crosswalk_mcp.loaders.sp800_53 import LoaderError
from tests.fixtures import tiny_fedramp_rules
from tests.test_tools import call


def test_loader_builds_rows():
    rows = fedramp.load(tiny_fedramp_rules(), "fedramp_rules", "abc")
    assert rows.document["version"] == "2026.01.01.01"
    assert [(t["id"], t["position"]) for t in rows.themes] == [
        ("KSI-CED", 0),
        ("KSI-CMT", 1),
    ]
    by_id = {i["id"]: i for i in rows.indicators}
    assert by_id["KSI-CED-RAT"]["statement"] == "Training is persistently reviewed."
    assert by_id["KSI-CED-RAT"]["theme_id"] == "KSI-CED"
    assert by_id["KSI-CED-VAR"]["statement"] is None
    assert by_id["KSI-CED-VAR"]["terms"] == "[]"  # missing in the file
    assert rows.indicator_classes == [
        {"indicator_id": "KSI-CED-VAR", "class": "c", "statement": "Do it."},
        {
            "indicator_id": "KSI-CED-VAR",
            "class": "b",
            "statement": "**Optional:** Do it.",
        },
    ]
    assert [
        (c["control_id"], c["oscal_id"], c["position"])
        for c in rows.indicator_controls
        if c["indicator_id"] == "KSI-CED-RAT"
    ] == [
        ("AC-2", "ac-2", 0),
        ("AC-2(10)", "ac-2.10", 1),
        ("AU-6", "au-6", 2),
        ("PL-4", "pl-4", 3),
    ]
    assert rows.definitions[0]["term"] == "Persistently"
    assert rows.definitions[0]["alts"] == '["persistently"]'
    guidance = {(g["control_id"], g["class"]): g for g in rows.control_guidance}
    assert set(guidance) == {("AC-2", None), ("AC-2(10)", "c"), ("AU-6", None)}
    assert guidance[("AC-2", None)]["guidance"] == '["Follow the guide."]'
    assert "daily" in guidance[("AC-2(10)", "c")]["parameters"]
    assert "Set." in guidance[("AU-6", None)]["updated"]


def test_loader_rejects_wrong_shape():
    with pytest.raises(LoaderError):
        fedramp.load({"info": {}}, "fedramp_rules", "abc")
    bad = tiny_fedramp_rules()
    bad["KSI"]["CED"]["indicators"]["KSI-CED-RAT"]["controls"] = ["not-a-control"]
    with pytest.raises(LoaderError, match="KSI-CED-RAT"):
        fedramp.load(bad, "fedramp_rules", "abc")


def test_store_reads_ksis(tiny_store_path: Path):
    s = store.open_store(tiny_store_path)
    assert s.fedramp_document()["title"] == "Test rules"
    assert s.fedramp_counts()["ksi_control_links"] == 5
    assert [(t["id"], t["indicator_count"]) for t in s.ksi_themes()] == [
        ("KSI-CED", 2),
        ("KSI-CMT", 1),
    ]
    theme = s.get_ksi_theme("KSI-CED")
    assert [
        (i["id"], i["varies_by_class"], i["control_count"]) for i in theme["indicators"]
    ] == [("KSI-CED-RAT", False, 4), ("KSI-CED-VAR", True, 0)]
    assert s.get_ksi_theme("KSI-ZZZ") is None

    rat = s.get_ksi("KSI-CED-RAT")
    assert rat["theme_name"] == "Cybersecurity Education"
    assert rat["classes"] == []
    assert [c["id"] for c in rat["controls"]] == ["AC-2", "AC-2(10)", "AU-6", "PL-4"]
    assert rat["terms"] == [
        {
            "term": "Persistently",
            "definition": "Repeated over time.",
            "note": "Not the same as continuously.",
        },
        {"term": "Undefined Term", "definition": None, "note": None},
    ]
    assert rat["updated"] == [{"date": "2026-01-01", "comment": "Launch."}]
    var = s.get_ksi("KSI-CED-VAR")
    assert [c["class"] for c in var["classes"]] == ["b", "c"]
    assert s.get_ksi("KSI-CED-NOPE") is None
    s.close()


async def test_get_ksi_lists_themes(tiny_store):
    result = await call("controls_get_ksi")
    assert result["themes"] == [
        {
            "id": "KSI-CED",
            "name": "Cybersecurity Education",
            "status": "stable",
            "indicator_count": 2,
        },
        {
            "id": "KSI-CMT",
            "name": "Change Management",
            "status": "stable",
            "indicator_count": 1,
        },
    ]
    assert result["provenance"]["source"]["key"] == "fedramp_rules"
    assert len(result["provenance"]["source"]["pin"]) == 40
    assert result["provenance"]["document"]["version"] == "2026.01.01.01"


async def test_get_ksi_theme(tiny_store):
    result = await call("controls_get_ksi", ksi_id="ksi-ced")
    theme = result["theme"]
    assert theme["id"] == "KSI-CED"
    assert [i["id"] for i in theme["indicators"]] == ["KSI-CED-RAT", "KSI-CED-VAR"]
    assert theme["indicators"][1]["varies_by_class"] is True
    citation = result["provenance"]["citation"]
    assert citation["json_path"] == "KSI.CED"
    assert "KSI-CED Cybersecurity Education" in citation["text"]


async def test_get_ksi_indicator(tiny_store):
    result = await call("controls_get_ksi", ksi_id="KSI-CED-RAT")
    indicator = result["indicator"]
    assert indicator["theme"] == {"id": "KSI-CED", "name": "Cybersecurity Education"}
    assert indicator["statement"] == "Training is persistently reviewed."
    assert indicator["statements_by_class"] is None
    assert indicator["terms"][0]["definition"] == "Repeated over time."

    related = result["related_controls"]
    assert related["relationship"] == "direct"
    assert related["publisher"] == "FedRAMP"
    assert related["catalog_release"] == "unspecified"
    assert related["resolved_against"] == "5.2.0"
    assert related["status"] == "published"
    assert related["count"] == 4
    assert related["controls"][0] == {
        "id": "AC-2",
        "oscal_id": "ac-2",
        "found": True,
        "title": "ACCOUNT MANAGEMENT",
        "withdrawn": False,
        "baselines": ["low", "moderate", "high"],
    }
    assert related["controls"][1]["withdrawn"] is True
    assert related["controls"][3] == {
        "id": "PL-4",
        "oscal_id": "pl-4",
        "found": False,
        "title": None,
        "withdrawn": None,
        "baselines": [],
    }
    notes = " ".join(result["notes"])
    assert "Related SP 800-53 Controls" in notes
    assert "Not in SP 800-53 release 5.2.0: PL-4" in notes
    assert "Withdrawn in SP 800-53 release 5.2.0: AC-2(10)" in notes
    citation = result["provenance"]["citation"]
    assert citation["json_path"] == "KSI.CED.indicators.KSI-CED-RAT"
    assert citation["url"].startswith("https://raw.githubusercontent.com/FedRAMP/")


async def test_get_ksi_indicator_varies_by_class(tiny_store):
    result = await call("controls_get_ksi", ksi_id="KSI-CED-VAR")
    indicator = result["indicator"]
    assert indicator["statement"] is None
    assert indicator["statements_by_class"] == {
        "b": "**Optional:** Do it.",
        "c": "Do it.",
    }
    assert result["related_controls"]["status"] == "none_published"
    assert result["related_controls"]["controls"] == []
    assert "authorization class" in result["notes"][0]
    assert "lists no related SP 800-53 controls" in result["notes"][1]


async def test_get_ksi_errors(tiny_store):
    with pytest.raises(ToolError, match="not a FedRAMP KSI identifier"):
        await call("controls_get_ksi", ksi_id="AC-2")
    with pytest.raises(ToolError, match="Themes: KSI-CED, KSI-CMT"):
        await call("controls_get_ksi", ksi_id="KSI-ZZZ")
    with pytest.raises(ToolError, match="Call with KSI-CED to list"):
        await call("controls_get_ksi", ksi_id="KSI-CED-NOPE")
    with pytest.raises(ToolError, match="Call with no id"):
        await call("controls_get_ksi", ksi_id="KSI-ZZZ-NOPE")


REAL_STORE = Path("data") / store.DB_NAME

# The five indicators whose statement varies by authorization class.
VARIES_BY_CLASS = [
    "KSI-CNA-EIS",
    "KSI-MLA-ALA",
    "KSI-SVC-PRR",
    "KSI-SVC-RUD",
    "KSI-SVC-VCM",
]


@pytest.mark.skipif(not REAL_STORE.exists(), reason="real store not built")
def test_real_store_matches_published_rules():
    s = store.open_store(REAL_STORE)
    counts = s.fedramp_counts()
    assert counts["ksi_themes"] == 10
    assert counts["ksi_indicators"] == 46
    assert counts["ksi_control_links"] == 558
    varies = [
        r["indicator_id"]
        for r in s.conn.execute(
            "SELECT DISTINCT indicator_id FROM fedramp_indicator_classes "
            "ORDER BY indicator_id"
        )
    ]
    assert varies == VARIES_BY_CLASS
    rat = s.get_ksi("KSI-CED-RAT")
    assert len(rat["controls"]) == 19
    assert rat["controls"][1] == {"id": "AT-2(2)", "oscal_id": "at-2.2"}
    assert rat["terms"][0]["term"] == "Incident"
    # Every related control exists in 5.2.0 and none is withdrawn.
    missing = s.conn.execute(
        "SELECT count(*) FROM fedramp_indicator_controls f "
        "LEFT JOIN controls c ON c.release = '5.2.0' AND c.id = f.control_id "
        "WHERE c.id IS NULL OR c.withdrawn = 1"
    ).fetchone()[0]
    assert missing == 0
    assert s.get_ksi("KSI-PIY-RES")["controls"] == []
    s.close()
