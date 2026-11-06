"""A tiny CPRT shaped export and a raw directory built from it.

Shared by the store and tool tests so both run offline against the same
small catalog: AC-2 with two items, one objective and one parameter, a
withdrawn enhancement AC-2(10), a withdrawn control AC-13, and AU-6.

The export comes in two flavors so the release comparison has something to
find. The newer flavor rewords AC-2 item a, renames its parameter, adds a
discussion paragraph, and adds a control AC-25 that AC-2 relates to.

A second tiny export, shaped like the CPRT CSF 2.0 file, holds two
functions with one active and one retired category; see tiny_csf_export.
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


CSF_DOC = "CSF_TEST"


def csf_element(element_type: str, ident: str, title: str = "", text: str = "") -> dict:
    return {**element(element_type, ident, title, text), "doc_identifier": CSF_DOC}


def csf_edge(src: str, dst: str, kind: str = "projection", dest_doc: str = CSF_DOC):
    return {
        **edge(src, dst, kind),
        "source_doc_identifier": CSF_DOC,
        "dest_doc_identifier": dest_doc,
        "provenance_doc_identifier": CSF_DOC,
    }


def tiny_csf_export() -> dict:
    """Two functions. GV holds category GV.OC with GV.OC-01 (two examples,
    a first party tag, references to the AC and AU families of the test
    800-53 document plus one family, PM, the test catalog lacks) and
    GV.OC-02 (no references). ID holds the retired CSF 1.1 category ID.BE,
    incorporated into GV.OC, with retired subcategory ID.BE-02, incorporated
    into GV.OC-01."""
    elements = [
        csf_element("function", "GV", "GOVERN", "Strategy is established."),
        csf_element("sort", "S-GV", "00001"),
        csf_element("category", "GV.OC", "Organizational Context", "Context."),
        csf_element("sort", "S-GV.OC", "00001.00001"),
        csf_element("subcategory", "GV.OC-01", "", "The mission is  understood"),
        csf_element("sort", "S-GV.OC-01", "00001.00001.00001"),
        csf_element("implementation_example", "GV.OC-01.002", "Ex2", "Second."),
        csf_element("implementation_example", "GV.OC-01.001", "Ex1", "Share it."),
        csf_element("party", "first", "1st", "1st Party Risk"),
        csf_element("subcategory", "GV.OC-02", "", "Stakeholders are understood"),
        csf_element("sort", "S-GV.OC-02", "00001.00001.00002"),
        csf_element("function", "ID", "IDENTIFY", "Risks are understood."),
        csf_element("sort", "S-ID", "00002"),
        csf_element("category", "ID.BE", "Business Environment"),
        csf_element("sort", "S-ID.BE", "00002.00002"),
        csf_element("withdraw_reason", "WR-ID.BE", "", "Incorporated into GV.OC"),
        csf_element("subcategory", "ID.BE-02", "", "Place in infrastructure"),
        csf_element("sort", "S-ID.BE-02", "00002.00002.00002"),
        csf_element("withdraw_reason", "WR-ID.BE-02", "", "Incorporated into GV.OC-01"),
    ]
    relationships = [
        csf_edge("GV", "GV.OC"),
        csf_edge("GV", "S-GV"),
        csf_edge("GV.OC", "GV.OC-01"),
        csf_edge("GV.OC", "GV.OC-02"),
        csf_edge("GV.OC", "S-GV.OC"),
        csf_edge("GV.OC-01", "S-GV.OC-01"),
        csf_edge("GV.OC-01", "GV.OC-01.002"),
        csf_edge("GV.OC-01", "GV.OC-01.001"),
        csf_edge("GV.OC-01", "first"),
        csf_edge("GV.OC-01", "AU", "external_reference", DOC),
        csf_edge("GV.OC-01", "AC", "external_reference", DOC),
        csf_edge("GV.OC", "PM", "external_reference", DOC),
        csf_edge("GV.OC-02", "S-GV.OC-02"),
        csf_edge("ID", "ID.BE"),
        csf_edge("ID", "S-ID"),
        csf_edge("ID.BE", "ID.BE-02"),
        csf_edge("ID.BE", "S-ID.BE"),
        csf_edge("ID.BE", "WR-ID.BE"),
        csf_edge("WR-ID.BE", "GV.OC", "incorporated_into"),
        csf_edge("ID.BE-02", "S-ID.BE-02"),
        csf_edge("ID.BE-02", "WR-ID.BE-02"),
        csf_edge("WR-ID.BE-02", "GV.OC-01", "incorporated_into"),
    ]
    return {
        "response": {
            "requestType": "elements",
            "elements": {
                "documents": [
                    {
                        "doc_identifier": CSF_DOC,
                        "name": "Test framework",
                        "version": "Version  2.0",
                        "website": "https://example.invalid/csf",
                    }
                ],
                "relationship_types": [],
                "elements": elements,
                "relationships": relationships,
            },
        }
    }


def tiny_fedramp_rules() -> dict:
    """Two KSI themes. KSI-CED-RAT relates to AC-2, the withdrawn AC-2(10),
    AU-6, and PL-4 (absent from the test catalog) and uses one defined
    term. KSI-CED-VAR varies by class and lists no controls. KSI-CMT-LMC
    relates to AU-6. CTL guidance covers AC-2 (all classes), AC-2(10)
    (class c only), and AU-6 (a parameter value)."""
    return {
        "info": {
            "title": "Test rules",
            "description": "",
            "version": "2026.01.01.01",
            "last_updated": "2026-01-01",
            "default_artifacts": {},
        },
        "FRD": {
            "info": {},
            "data": {
                "all": {
                    "FRD-PER": {
                        "term": "Persistently",
                        "definition": "Repeated over time.",
                        "note": "Not the same as continuously.",
                        "tag": "General",
                        "alts": ["persistently"],
                    }
                }
            },
        },
        "FRR": {},
        "KSI": {
            "CED": {
                "id": "KSI-CED",
                "name": "Cybersecurity Education",
                "web_name": "cybersecurity-education",
                "short_name": "CED",
                "status": "stable",
                "indicators": {
                    "KSI-CED-RAT": {
                        "name": "Reviewing All Training",
                        "statement": "Training is persistently reviewed.",
                        "controls": ["ac-2", "ac-2.10", "au-6", "pl-4"],
                        "updated": [{"date": "2026-01-01", "comment": "Launch."}],
                        "terms": ["Persistently", "Undefined Term"],
                    },
                    "KSI-CED-VAR": {
                        "name": "Varies",
                        "varies_by_class": {
                            "c": {"statement": "Do it."},
                            "b": {"statement": "**Optional:** Do it."},
                        },
                        "controls": [],
                        "updated": [],
                    },
                },
            },
            "CMT": {
                "id": "KSI-CMT",
                "name": "Change Management",
                "web_name": "change-management",
                "short_name": "CMT",
                "status": "stable",
                "indicators": {
                    "KSI-CMT-LMC": {
                        "name": "Log Changes",
                        "statement": "Changes are logged.",
                        "controls": ["au-6"],
                        "updated": [],
                        "terms": [],
                    }
                },
            },
        },
        "CTL": {
            "AC": {
                "AC-02": {"guidance": ["Follow the guide."]},
                "AC-02-10": {
                    "varies_by_class": {
                        "c": {
                            "parameters": [
                                {"parameterId": "ac-02.10_odp", "value": "daily"}
                            ]
                        }
                    }
                },
            },
            "AU": {
                "AU-06": {
                    "parameters": [{"parameterId": "au-06_odp.01", "value": "weekly"}],
                    "updated": [{"date": "2026-01-01", "comment": "Set."}],
                }
            },
        },
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
        elif source.key == "csf_2_0_0":
            path.write_text(json.dumps(tiny_csf_export()), encoding="utf-8")
        elif source.key == "fedramp_rules":
            path.write_text(json.dumps(tiny_fedramp_rules()), encoding="utf-8")
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
