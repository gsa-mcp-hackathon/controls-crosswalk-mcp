"""Tests for the 800-53 loader and the SQLite store.

The loader tests use a small hand built export shaped like a CPRT file, so
they run offline and fast. A final test uses the real store when it exists.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from crosswalk_mcp import snapshot, store
from crosswalk_mcp.loaders import sp800_53
from crosswalk_mcp.loaders.common import html_to_text, natural_key
from crosswalk_mcp.sources import SOURCES
from tests.fixtures import DOC, tiny_export, write_raw_dir


def test_html_to_text_flattens_paragraphs_and_entities():
    assert html_to_text("<p>First &amp; second.</p><p>Third.</p>") == (
        "First & second.\n\nThird."
    )
    assert html_to_text("") == ""
    assert html_to_text('<p class="MsoNormal"><span>a  b</span></p>') == "a b"


def test_natural_key_orders_letters_and_numbers():
    assert sorted(["b", "10", "a", "2", "1"], key=natural_key) == [
        "1",
        "2",
        "10",
        "a",
        "b",
    ]


def test_loader_builds_control_rows():
    rows = sp800_53.load(tiny_export(), "9.9.9", "test_key", "abc")
    assert rows.release["doc_identifier"] == DOC
    assert [f["id"] for f in rows.families] == ["AC"]

    by_id = {c["id"]: c for c in rows.controls}
    assert set(by_id) == {"AC-2", "AC-2(10)", "AC-13", "AU-6"}
    ac2 = by_id["AC-2"]
    assert ac2["cprt_id"] == "AC-02"
    assert ac2["oscal_id"] == "ac-2"
    assert ac2["title"] == "ACCOUNT MANAGEMENT"
    assert ac2["parent_id"] is None
    assert ac2["withdrawn"] == 0
    assert ac2["sort_key"] == "00001.00002"
    assert ac2["discussion"] == "First & second.\n\nThird."
    # Items are ordered by label even though the file lists b before a.
    assert (
        ac2["statement_text"]
        == "a. Define account types;\n  b. Assign account managers;"
    )

    enhancement = by_id["AC-2(10)"]
    assert enhancement["parent_id"] == "AC-2"
    assert enhancement["withdrawn"] == 1
    assert enhancement["withdraw_reason"] == "Incorporated into AC-2"


def test_loader_builds_child_rows():
    rows = sp800_53.load(tiny_export(), "9.9.9", "test_key", "abc")

    labels = [
        (s["id"], s["label"], s["depth"])
        for s in rows.statements
        if s["control_id"] == "AC-2"
    ]
    assert labels == [
        ("CST-AC-02", None, 0),
        ("CST-AC-02-a", "a", 1),
        ("CST-AC-02-b", "b", 1),
    ]

    assert len(rows.objectives) == 1
    objective = rows.objectives[0]
    assert objective["statement_id"] == "CST-AC-02-a"
    assert json.loads(objective["parameter_ids"]) == ["AC-02_ODP[01]"]

    assert len(rows.parameters) == 1
    parameter = rows.parameters[0]
    assert parameter["kind"] == "assignment"
    assert parameter["label"] == "prerequisites"
    assert parameter["statement"] == "organization-defined prerequisites"
    assert parameter["choices"] is None

    assert rows.assessment_methods == [
        {
            "release": "9.9.9",
            "control_id": "AC-2",
            "method": "examine",
            "text": "[SELECT FROM: Access control policy].",
        }
    ]
    # The duplicated projection to the same reference is collapsed.
    assert len(rows.control_references) == 1
    assert rows.control_references[0]["url"].endswith("800-162")

    baselines = sorted((b["control_id"], b["baseline"]) for b in rows.cprt_baselines)
    assert baselines == [("AC-2", "low"), ("AC-2", "moderate")]

    relations = sorted(
        (r["source_id"], r["dest_id"], r["kind"]) for r in rows.control_relations
    )
    assert relations == [
        ("AC-13", "AC-2", "incorporated_into"),
        ("AC-13", "AU-6", "incorporated_into"),
        ("AC-2", "AU-6", "related"),
        ("AC-2(10)", "AC-2", "incorporated_into"),
    ]


def test_loader_rejects_wrong_shape():
    with pytest.raises(sp800_53.LoaderError):
        sp800_53.load({"catalog": {}}, "1", "k", "s")


def test_build_and_open_store(tmp_path: Path):
    raw = write_raw_dir(tmp_path)
    out = tmp_path / "store.sqlite"
    report = store.build(raw, out)
    assert report.path == out
    assert report.counts["controls"] == 8  # four controls in each of two releases
    assert not out.with_suffix(".sqlite.part").exists()

    s = store.open_store(out)
    meta = s.meta()
    assert meta["schema_version"] == str(store.SCHEMA_VERSION)
    assert meta["manifest_hash"] == snapshot.read_manifest(raw)["manifest_hash"]
    assert {src["key"] for src in meta["sources"]} == {src.key for src in SOURCES}
    assert [r["release"] for r in s.releases()] == ["5.2.0", "5.1.1"]
    assert s.default_release() == "5.2.0"
    assert s.has_release("5.1.1") and not s.has_release("4.0.0")

    ac2 = s.get_control("AC-2", "5.2.0")
    assert ac2["family_title"] == "ACCESS CONTROL"
    assert ac2["statement"][0]["items"][0]["label"] == "a"
    assert ac2["parameters"][0]["id"] == "AC-02_ODP[01]"
    assert ac2["objectives"][0]["parameter_ids"] == ["AC-02_ODP[01]"]
    assert ac2["assessment_methods"] == {
        "examine": "[SELECT FROM: Access control policy]."
    }
    assert ac2["related"] == ["AU-6"]
    assert ac2["enhancements"] == [
        {"id": "AC-2(10)", "title": "SHARED CREDENTIAL CHANGE", "withdrawn": True}
    ]
    assert ac2["cprt_baselines"] == ["low", "moderate"]
    assert ac2["privacy_baseline"] is False

    ac13 = s.get_control("AC-13", "5.2.0")
    assert ac13["withdrawn"] is True
    assert sorted(ac13["incorporated_into"]) == ["AC-2", "AU-6"]
    assert s.get_control("AC-99", "5.2.0") is None

    hits = s.conn.execute(
        "SELECT id FROM controls_fts "
        "WHERE controls_fts MATCH 'managers' AND release = '5.2.0'"
    ).fetchall()
    assert [h["id"] for h in hits] == ["AC-2"]

    # The connection is read only.
    with pytest.raises(sqlite3.OperationalError):
        s.conn.execute("DELETE FROM controls")
    s.close()


def test_build_refuses_unverified_snapshot(tmp_path: Path):
    raw = write_raw_dir(tmp_path)
    (raw / SOURCES[0].filename).write_text('{"tampered": true}', encoding="utf-8")
    with pytest.raises(store.StoreError, match="does not verify"):
        store.build(raw, tmp_path / "store.sqlite")


def test_open_store_reports_missing_and_stale(tmp_path: Path):
    with pytest.raises(store.StoreError, match="No store"):
        store.open_store(tmp_path / "missing.sqlite")

    raw = write_raw_dir(tmp_path)
    out = tmp_path / "store.sqlite"
    store.build(raw, out)
    conn = sqlite3.connect(out)
    conn.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(store.StoreError, match="Rebuild"):
        store.open_store(out)


REAL_STORE = Path("data") / store.DB_NAME


@pytest.mark.skipif(not REAL_STORE.exists(), reason="real store not built")
def test_real_store_has_known_facts():
    """A few facts from the published catalog, checked against the real build."""
    s = store.open_store(REAL_STORE)
    ac2 = s.get_control("AC-2", "5.2.0")
    assert ac2["title"] == "ACCOUNT MANAGEMENT"
    assert ac2["cprt_baselines"] == ["low", "moderate", "high"]
    assert len(ac2["enhancements"]) == 13
    assert [p["id"] for p in ac2["parameters"]][:2] == [
        "AC-02_ODP[01]",
        "AC-02_ODP[02]",
    ]
    assert s.get_control("SA-24", "5.2.0") is not None
    assert s.get_control("SA-24", "5.1.1") is None
    ca34 = s.get_control("CA-3(4)", "5.2.0")
    assert ca34["withdrawn"] and ca34["moved_to"] == ["SC-7(28)"]
    s.close()
