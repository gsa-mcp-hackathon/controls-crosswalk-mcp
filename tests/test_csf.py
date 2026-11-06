"""Tests for the CSF 2.0 loader, its store tables, and the lookup tool.

The loader and store tests use the tiny CSF export in fixtures.py. A final
test checks the real store, when it is built, against the published list of
active CSF 2.0 subcategories.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from crosswalk_mcp import store
from crosswalk_mcp.loaders import csf
from crosswalk_mcp.loaders.sp800_53 import LoaderError
from tests.fixtures import CSF_DOC, tiny_csf_export
from tests.test_tools import call


def test_parent_of_follows_the_identifier():
    assert csf.parent_of("GV") is None
    assert csf.parent_of("GV.OC") == "GV"
    assert csf.parent_of("GV.OC-01") == "GV.OC"
    assert csf.parent_of("de.dp-5") == "DE.DP"


def test_loader_builds_element_rows():
    rows = csf.load(tiny_csf_export(), "csf_2_0_0", "abc")
    assert rows.document["doc_identifier"] == CSF_DOC
    assert rows.document["version"] == "Version 2.0"

    by_id = {e["id"]: e for e in rows.elements}
    assert set(by_id) == {
        "GV",
        "GV.OC",
        "GV.OC-01",
        "GV.OC-02",
        "ID",
        "ID.BE",
        "ID.BE-02",
    }
    assert by_id["GV"] == {
        "id": "GV",
        "kind": "function",
        "parent_id": None,
        "function_id": "GV",
        "title": "GOVERN",
        "text": "Strategy is established.",
        "sort_key": "00001",
        "legacy": 0,
        "legacy_note": None,
    }
    sub = by_id["GV.OC-01"]
    assert sub["kind"] == "subcategory"
    assert sub["parent_id"] == "GV.OC"
    assert sub["text"] == "The mission is understood"  # whitespace collapsed
    assert sub["sort_key"] == "00001.00001.00001"
    legacy = by_id["ID.BE-02"]
    assert legacy["legacy"] == 1
    assert legacy["legacy_note"] == "Incorporated into GV.OC-01"

    # Examples come back in label order even though the file lists Ex2 first.
    assert [(e["id"], e["label"], e["position"]) for e in rows.examples] == [
        ("GV.OC-01.001", "Ex1", 0),
        ("GV.OC-01.002", "Ex2", 1),
    ]
    assert rows.tags == [
        {"element_id": "GV.OC-01", "tag": "first", "label": "1st Party Risk"}
    ]
    assert rows.relations == [
        {"source_id": "ID.BE", "dest_id": "GV.OC", "kind": "incorporated_into"},
        {"source_id": "ID.BE-02", "dest_id": "GV.OC-01", "kind": "incorporated_into"},
    ]
    assert {r["target_id"] for r in rows.references} == {"AC", "AU", "PM"}
    assert all(r["target_doc"] == "SP_800_53_TEST" for r in rows.references)


def test_loader_rejects_wrong_shape():
    with pytest.raises(LoaderError):
        csf.load({"response": {}}, "csf_2_0_0", "abc")


def test_store_reads_csf_elements(tiny_store_path: Path):
    s = store.open_store(tiny_store_path)
    assert s.csf_document()["name"] == "Test framework"
    assert s.csf_counts() == {
        "active": {"function": 2, "category": 1, "subcategory": 2},
        "legacy": {"category": 1, "subcategory": 1},
    }
    gv = s.get_csf_element("GV")
    assert [c["id"] for c in gv["children"]] == ["GV.OC"]
    sub = s.get_csf_element("GV.OC-01")
    assert sub["legacy"] is False
    assert [e["label"] for e in sub["examples"]] == ["Ex1", "Ex2"]
    assert sub["tags"] == [{"tag": "first", "label": "1st Party Risk"}]
    assert [r["target_id"] for r in sub["references"]] == ["AC", "AU"]
    assert [r["target_id"] for r in s.get_csf_element("GV.OC")["references"]] == ["PM"]
    assert sub["legacy_sources"] == [{"id": "ID.BE-02", "kind": "incorporated_into"}]
    legacy = s.get_csf_element("ID.BE")
    assert legacy["legacy"] is True
    assert legacy["incorporated_into"] == ["GV.OC"]
    assert [c["legacy"] for c in legacy["children"]] == [True]
    assert s.get_csf_element("PR.AA") is None
    assert s.release_for_document("SP_800_53_TEST") == "5.1.1"
    assert s.release_for_document("NOPE") is None
    s.close()


async def test_get_csf_element_subcategory(tiny_store):
    result = await call("controls_get_csf_element", csf_id="gv.oc-1")
    element = result["element"]
    assert element["id"] == "GV.OC-01"
    assert element["kind"] == "subcategory"
    assert element["status"] == "active"
    assert element["function"] == {"id": "GV", "title": "GOVERN"}
    assert element["category"] == {"id": "GV.OC", "title": "Organizational Context"}
    assert element["risk_tags"] == ["1st Party Risk"]
    assert [e["label"] for e in element["implementation_examples"]] == ["Ex1", "Ex2"]
    assert element["legacy_sources"] == [
        {"id": "ID.BE-02", "kind": "incorporated_into"}
    ]
    assert element["children"] == []

    refs = result["sp800_53_references"]
    assert refs["status"] == "published"
    assert refs["relationship"] == "direct"
    assert refs["level"] == "family"
    assert refs["target_document"] == "SP_800_53_TEST"
    assert refs["target_release"] == "5.1.1"
    assert refs["interpreted_against"] == "5.2.0"
    assert refs["families"] == [
        {"id": "AC", "title": "ACCESS CONTROL"},
        {"id": "AU", "title": "AUDIT AND ACCOUNTABILITY"},
    ]
    assert any("family level" in note for note in result["notes"])
    assert any(
        "published against SP 800-53 release 5.1.1" in n for n in result["notes"]
    )

    provenance = result["provenance"]
    assert provenance["source"]["key"] == "csf_2_0_0"
    assert provenance["document"]["url"] == "https://example.invalid/csf"
    assert provenance["citation"]["url"].endswith("CSF_TEST/home?element=GV.OC-01")
    assert "subcategory GV.OC-01" in provenance["citation"]["text"]


async def test_get_csf_element_category_with_unknown_family(tiny_store):
    result = await call("controls_get_csf_element", csf_id="GV.OC")
    assert [c["id"] for c in result["element"]["children"]] == [
        "GV.OC-01",
        "GV.OC-02",
    ]
    assert result["element"]["legacy_sources"] == [
        {"id": "ID.BE", "kind": "incorporated_into"}
    ]
    refs = result["sp800_53_references"]
    assert refs["status"] == "published"
    assert refs["families"] == [{"id": "PM", "title": None}]
    assert "interpreted_against" not in refs
    assert any(
        "Not a family in SP 800-53 release 5.1.1: PM" in n for n in result["notes"]
    )
    assert any("Not a family in release 5.2.0: PM" in n for n in result["notes"])


async def test_get_csf_element_none_published_and_function(tiny_store):
    result = await call("controls_get_csf_element", csf_id="GV.OC-02")
    assert result["sp800_53_references"] == {
        "relationship": "direct",
        "level": "family",
        "publisher": "NIST",
        "status": "none_published",
        "families": [],
    }
    assert "not a statement that no control applies" in result["notes"][0]

    result = await call("controls_get_csf_element", csf_id="gv")
    assert result["element"]["function"] is None
    assert result["element"]["category"] is None
    assert [c["id"] for c in result["element"]["children"]] == ["GV.OC"]
    assert result["sp800_53_references"]["status"] == "not_applicable"
    assert "GOVERN" in result["provenance"]["citation"]["text"]


async def test_get_csf_element_legacy(tiny_store):
    result = await call("controls_get_csf_element", csf_id="ID")
    assert result["element"]["children"] == []
    assert "1 retired CSF 1.1 identifier(s) under ID" in result["notes"][0]

    result = await call("controls_get_csf_element", csf_id="ID", include_legacy=True)
    assert [(c["id"], c["status"]) for c in result["element"]["children"]] == [
        ("ID.BE", "legacy")
    ]

    result = await call("controls_get_csf_element", csf_id="ID.BE-2")
    element = result["element"]
    assert element["status"] == "legacy"
    assert element["legacy_note"] == "Incorporated into GV.OC-01"
    assert element["incorporated_into"] == ["GV.OC-01"]
    assert "retired" in result["notes"][0]


async def test_get_csf_element_errors(tiny_store):
    with pytest.raises(ToolError, match="not a CSF identifier"):
        await call("controls_get_csf_element", csf_id="AC-2")
    with pytest.raises(ToolError, match="Functions are GV, ID, PR, DE, RS, and RC"):
        await call("controls_get_csf_element", csf_id="PR.AA-01")


REAL_STORE = Path("data") / store.DB_NAME

# The 106 subcategories of the CSF 2.0 core, from NIST CSWP 29 Appendix A.
# Compared as sets: CPRT orders the DETECT categories DE.AE then DE.CM,
# while the publication lists DE.CM first.
ACTIVE_SUBCATEGORIES = [
    *(f"GV.OC-{n:02d}" for n in range(1, 6)),
    *(f"GV.RM-{n:02d}" for n in range(1, 8)),
    *(f"GV.RR-{n:02d}" for n in range(1, 5)),
    *(f"GV.PO-{n:02d}" for n in range(1, 3)),
    *(f"GV.OV-{n:02d}" for n in range(1, 4)),
    *(f"GV.SC-{n:02d}" for n in range(1, 11)),
    *(f"ID.AM-{n:02d}" for n in (1, 2, 3, 4, 5, 7, 8)),
    *(f"ID.RA-{n:02d}" for n in range(1, 11)),
    *(f"ID.IM-{n:02d}" for n in range(1, 5)),
    *(f"PR.AA-{n:02d}" for n in range(1, 7)),
    *(f"PR.AT-{n:02d}" for n in range(1, 3)),
    *(f"PR.DS-{n:02d}" for n in (1, 2, 10, 11)),
    *(f"PR.PS-{n:02d}" for n in range(1, 7)),
    *(f"PR.IR-{n:02d}" for n in range(1, 5)),
    *(f"DE.CM-{n:02d}" for n in (1, 2, 3, 6, 9)),
    *(f"DE.AE-{n:02d}" for n in (2, 3, 4, 6, 7, 8)),
    *(f"RS.MA-{n:02d}" for n in range(1, 6)),
    *(f"RS.AN-{n:02d}" for n in (3, 6, 7, 8)),
    *(f"RS.CO-{n:02d}" for n in (2, 3)),
    *(f"RS.MI-{n:02d}" for n in (1, 2)),
    *(f"RC.RP-{n:02d}" for n in range(1, 7)),
    *(f"RC.CO-{n:02d}" for n in (3, 4)),
]


@pytest.mark.skipif(not REAL_STORE.exists(), reason="real store not built")
def test_real_store_matches_published_csf():
    s = store.open_store(REAL_STORE)
    active = [
        row["id"]
        for row in s.conn.execute(
            "SELECT id FROM csf_elements WHERE kind = 'subcategory' AND legacy = 0 "
            "ORDER BY sort_key"
        )
    ]
    assert sorted(active) == sorted(ACTIVE_SUBCATEGORIES)
    assert len(active) == 106
    functions = s.conn.execute(
        "SELECT id FROM csf_elements WHERE kind = 'function' ORDER BY sort_key"
    ).fetchall()
    assert [f["id"] for f in functions] == ["GV", "ID", "PR", "DE", "RS", "RC"]
    s.close()
