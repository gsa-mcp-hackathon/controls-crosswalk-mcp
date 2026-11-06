"""A tiny CPRT shaped export and a raw directory built from it.

Shared by the store and tool tests so both run offline against the same
small catalog: AC-2 with two items, one objective and one parameter, a
withdrawn enhancement AC-2(10), a withdrawn control AC-13, and AU-6.

The export comes in two flavors so the release comparison has something to
find. The newer flavor rewords AC-2 item a, renames its parameter, adds a
discussion paragraph, and adds a control AC-25 that AC-2 relates to.
"""

from __future__ import annotations

import json
from pathlib import Path

from crosswalk_mcp import snapshot
from crosswalk_mcp.sources import SOURCES

DOC = "SP_800_53_TEST"


def element(element_type: str, ident: str, title: str = "", text: str = "") -> dict:
    return {
        "element_type": element_type,
        "element_identifier": ident,
        "title": title,
        "text": text,
        "doc_identifier": DOC,
    }


def edge(src: str, dst: str, kind: str = "projection") -> dict:
    return {
        "source_element_identifier": src,
        "source_doc_identifier": DOC,
        "dest_element_identifier": dst,
        "dest_doc_identifier": DOC,
        "relationship_identifier": kind,
        "provenance_doc_identifier": DOC,
    }


def tiny_export(newer: bool = False) -> dict:
    """AC family with AC-2 (two items, one objective, one parameter), a
    withdrawn enhancement AC-2(10), and a withdrawn control AC-13. With
    newer=True, the changes described at the top of this file are applied."""
    item_a = "Define and document account types;" if newer else "Define account types;"
    odp_label = "account prerequisites" if newer else "prerequisites"
    discussion = "<p>First &amp; second.</p><p>Third.</p>"
    if newer:
        discussion += "<p>Fourth.</p>"
    elements = [
        element("family", "AC", "ACCESS CONTROL"),
        element("family", "AU", "AUDIT AND ACCOUNTABILITY"),
        element("control", "AC-02", "ACCOUNT MANAGEMENT "),
        element("sort", "S-AC-02", "00001.00002"),
        element("control_statement", "CST-AC-02"),
        element("control_statement", "CST-AC-02-b", "b", "Assign account managers;"),
        element("control_statement", "CST-AC-02-a", "a", item_a),
        element(
            "determination",
            "DS-AC-02a.",
            "",
            "account types are <AC-02_ODP[01] x> defined;",
        ),
        element("odp", "AC-02_ODP[01]", odp_label, "prerequisites are defined;"),
        element("odp_type", "single_entry", "Assignment"),
        element(
            "odp_statement",
            "OS-ac-02_odp[01]",
            "",
            "organization-defined prerequisites",
        ),
        element("discussion", "D-AC-02", "", discussion),
        element("examine", "E-AC-02", "", "[SELECT FROM: Access control policy]."),
        element(
            "reference",
            "SP 800-162",
            "Guide to ABAC",
            "https://doi.org/10.6028/NIST.SP.800-162",
        ),
        element("security_baseline", "SB-Low", "Low"),
        element("security_baseline", "SB-Moderate", "Moderate"),
        element("privacy_baseline", "PB-No", "No"),
        element("control_enhancement", "AC-02(10)", "SHARED CREDENTIAL CHANGE"),
        element("sort", "S-AC-02(10)", "00001.00002.00010"),
        element("withdraw_reason", "WR-AC-02(10)", "", "Incorporated into AC-2"),
        element("control_statement", "CST-AC-02(10)", "", "Withdrawn"),
        element("control", "AC-13", "SUPERVISION AND REVIEW"),
        element("sort", "S-AC-13", "00001.00013"),
        element("withdraw_reason", "WR-AC-13", "", "Incorporated into AC-2, AU-6"),
        element("control_statement", "CST-AC-13", "", "Withdrawn"),
        element("control", "AU-06", "AUDIT RECORD REVIEW"),
        element("sort", "S-AU-06", "00003.00006"),
        element("control_statement", "CST-AU-06", "", "Review audit records."),
    ]
    relationships = [
        edge("AC", "AC-02"),
        edge("AC", "AC-13"),
        edge("AU", "AU-06"),
        edge("AC-02", "S-AC-02"),
        edge("AC-02", "CST-AC-02"),
        edge("CST-AC-02", "CST-AC-02-b"),
        edge("CST-AC-02", "CST-AC-02-a"),
        edge("CST-AC-02-a", "DS-AC-02a."),
        edge("DS-AC-02a.", "AC-02_ODP[01]"),
        edge("AC-02_ODP[01]", "single_entry"),
        edge("AC-02_ODP[01]", "OS-ac-02_odp[01]"),
        edge("AC-02", "D-AC-02"),
        edge("AC-02", "E-AC-02"),
        edge("AC-02", "SP 800-162"),
        edge("AC-02", "SP 800-162"),
        edge("AC-02", "SB-Low"),
        edge("AC-02", "SB-Moderate"),
        edge("AC-02", "PB-No"),
        edge("AC-02", "AC-02(10)"),
        edge("AC-02", "AU-06", "related"),
        edge("AC-02(10)", "S-AC-02(10)"),
        edge("AC-02(10)", "WR-AC-02(10)"),
        edge("AC-02(10)", "CST-AC-02(10)"),
        edge("WR-AC-02(10)", "AC-02", "incorporated_into"),
        edge("AC-13", "S-AC-13"),
        edge("AC-13", "WR-AC-13"),
        edge("AC-13", "CST-AC-13"),
        edge("WR-AC-13", "AC-02", "incorporated_into"),
        edge("WR-AC-13", "AU-06", "incorporated_into"),
        edge("AU-06", "S-AU-06"),
        edge("AU-06", "CST-AU-06"),
    ]
    if newer:
        elements += [
            element("control", "AC-25", "REFERENCE MONITOR"),
            element("sort", "S-AC-25", "00001.00025"),
            element(
                "control_statement", "CST-AC-25", "", "Implement a reference monitor."
            ),
        ]
        relationships += [
            edge("AC", "AC-25"),
            edge("AC-25", "S-AC-25"),
            edge("AC-25", "CST-AC-25"),
            edge("AC-02", "AC-25", "related"),
        ]
    return {
        "response": {
            "requestType": "elements",
            "elements": {
                "documents": [
                    {
                        "doc_identifier": DOC,
                        "name": "Test catalog",
                        "version": "9.9.9",
                        "website": "https://example.invalid/",
                    }
                ],
                "relationship_types": [],
                "elements": elements,
                "relationships": relationships,
            },
        }
    }


BASELINE_MEMBERS = {
    "low": ["ac-2"],
    "moderate": ["ac-2", "au-6"],
    "high": ["ac-2", "au-6"],
    "privacy": ["au-6"],
}


def tiny_baseline(level: str) -> dict:
    """An OSCAL resolved catalog with the members in BASELINE_MEMBERS."""
    titles = {"ac-2": "Account Management", "au-6": "Audit Record Review"}
    groups: dict[str, dict] = {}
    for oscal_id in BASELINE_MEMBERS[level]:
        family = oscal_id.split("-")[0]
        group = groups.setdefault(
            family, {"id": family, "title": family, "controls": []}
        )
        group["controls"].append({"id": oscal_id, "title": titles[oscal_id]})
    # The real HIGH file has this title mismatch; keep it so tests cover it.
    named = "5.1.1" if level == "high" else "9.9.9"
    return {
        "catalog": {
            "uuid": f"00000000-0000-0000-0000-0000000000{len(level):02d}",
            "metadata": {
                "title": f"Test {named} {level.upper()} baseline",
                "version": "9.9.9",
                "oscal-version": "1.2.3",
                "last-modified": "2026-01-01T00:00:00Z",
            },
            "groups": list(groups.values()),
        }
    }


def write_raw_dir(tmp_path: Path) -> Path:
    """A raw dir whose 800-53 files are the tiny export (the newer flavor for
    5.2.0), whose baseline files are tiny OSCAL catalogs, and whose other
    sources are empty JSON objects, with a manifest that verifies."""
    raw = tmp_path / "raw"
    raw.mkdir()
    entries = []
    for source in SOURCES:
        path = raw / source.filename
        if source.key.startswith("sp800_53"):
            newer = source.key == "sp800_53_5_2_0"
            path.write_text(json.dumps(tiny_export(newer)), encoding="utf-8")
        elif source.key.startswith("baseline_"):
            level = source.key.removeprefix("baseline_")
            path.write_text(json.dumps(tiny_baseline(level)), encoding="utf-8")
        else:
            path.write_text("{}", encoding="utf-8")
        entries.append(
            snapshot.ManifestEntry(
                key=source.key,
                url=source.url,
                pin=source.pin,
                filename=source.filename,
                bytes=path.stat().st_size,
                sha256=snapshot.sha256_file(path),
                fetched_at="test",
            )
        )
    snapshot.write_manifest(entries, raw)
    return raw
