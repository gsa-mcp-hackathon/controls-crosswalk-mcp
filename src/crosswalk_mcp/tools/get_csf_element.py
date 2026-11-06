"""controls_get_csf_element: one CSF 2.0 function, category, or subcategory.

The informative references to SP 800-53 that CPRT publishes for CSF 2.0
name families, not controls, and target release 5.1.1. This tool returns
them exactly that way and says so, rather than guessing at controls.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from crosswalk_mcp.ids import InvalidIdentifier, normalize_csf_id
from crosswalk_mcp.store import CSF_SOURCE, Store
from crosswalk_mcp.tools.common import (
    csf_citation,
    get_store,
    snapshot_provenance,
    source_record,
)

FAMILY_NOTE = (
    "CPRT publishes CSF 2.0 informative references to SP 800-53 at the family "
    "level, not to individual controls. To find controls within a family, use "
    "controls_search with the family filter, or controls_get_baseline."
)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="controls_get_csf_element",
        annotations={
            "title": "Get a CSF 2.0 function, category, or subcategory",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def controls_get_csf_element(
        csf_id: Annotated[
            str,
            Field(
                description=(
                    "A CSF 2.0 function (GV), category (PR.AA), or subcategory "
                    "(PR.AA-01). Retired CSF 1.1 identifiers such as DE.DP-5 are "
                    "accepted and reported as legacy."
                )
            ),
        ],
        include_legacy: Annotated[
            bool,
            Field(
                description=(
                    "Also list retired CSF 1.1 identifiers among the children of "
                    "a function or category. Off by default."
                )
            ),
        ] = False,
    ) -> dict:
        """Return one element of the NIST Cybersecurity Framework (CSF) 2.0
        core: a function, a category, or a subcategory.

        A function lists its categories and a category lists its
        subcategories, so three calls walk from GV to GV.OC to GV.OC-01. A
        subcategory includes its implementation examples and the SP 800-53
        families NIST publishes as informative references. Those references
        are family level and target SP 800-53 release 5.1.1, exactly as CPRT
        publishes them; the result labels them that way. Retired CSF 1.1
        identifiers are returned with status "legacy" and a note saying
        where their content went.
        """
        store = get_store()
        wanted = _resolve_csf_id(csf_id)
        with store.lock:
            record = store.get_csf_element(wanted)
            if record is None:
                raise ToolError(
                    f"{wanted} is not in CSF 2.0 or in the retired CSF 1.1 "
                    "identifiers CPRT keeps. Functions are GV, ID, PR, DE, RS, "
                    "and RC. Look up a function to list its categories, then a "
                    "category to list its subcategories."
                )
            document = store.csf_document()
            names = _names(store, [record["function_id"], record["parent_id"]])
            references, reference_notes = _references(store, record)

        notes: list[str] = []
        if record["legacy"]:
            notes.append(
                f"{wanted} is a CSF 1.1 identifier that CSF 2.0 retired: "
                f"{record['legacy_note']}. Look up the identifiers it was "
                "incorporated into or moved to for the current text."
            )
        children = record["children"]
        if not include_legacy:
            hidden = sum(1 for child in children if child["legacy"])
            children = [child for child in children if not child["legacy"]]
            if hidden:
                notes.append(
                    f"{hidden} retired CSF 1.1 identifier(s) under {wanted} are not "
                    "listed. Set include_legacy to see them."
                )
        notes.extend(reference_notes)

        kind = record["kind"]
        element = {
            "id": wanted,
            "kind": kind,
            "status": "legacy" if record["legacy"] else "active",
            "title": record["title"],
            "text": record["text"],
            "function": (
                None
                if kind == "function"
                else {
                    "id": record["function_id"],
                    "title": names[record["function_id"]],
                }
            ),
            "category": (
                {"id": record["parent_id"], "title": names[record["parent_id"]]}
                if kind == "subcategory"
                else None
            ),
            "legacy_note": record["legacy_note"],
            "incorporated_into": record["incorporated_into"],
            "moved_to": record["moved_to"],
            "legacy_sources": record["legacy_sources"],
            "risk_tags": [tag["label"] for tag in record["tags"]],
            "implementation_examples": record["examples"],
            "children": [
                {**child, "status": "legacy" if child.pop("legacy") else "active"}
                for child in children
            ],
        }
        return {
            "element": element,
            "sp800_53_references": references,
            "notes": notes,
            "provenance": {
                **snapshot_provenance(store),
                "source": source_record(store, CSF_SOURCE),
                "document": {
                    "name": document["name"],
                    "version": document["version"],
                    "url": document["website"],
                },
                "citation": csf_citation(document, record),
            },
        }


def _resolve_csf_id(raw: str) -> str:
    try:
        return normalize_csf_id(raw)
    except InvalidIdentifier:
        raise ToolError(
            f"'{raw}' is not a CSF identifier. Use a function (GV, ID, PR, DE, "
            "RS, RC), a category such as PR.AA, or a subcategory such as "
            "PR.AA-01."
        ) from None


def _names(store: Store, ids: list[str | None]) -> dict[str, str]:
    """Titles for the given element ids. Caller holds the store lock."""
    wanted = [i for i in ids if i]
    if not wanted:
        return {}
    rows = store.conn.execute(
        "SELECT id, title FROM csf_elements "
        f"WHERE id IN ({', '.join('?' for _ in wanted)})",
        wanted,
    ).fetchall()
    return {row["id"]: row["title"] for row in rows}


def _references(store: Store, record: dict) -> tuple[dict, list[str]]:
    """The published SP 800-53 references, labeled as published, plus notes.
    Caller holds the store lock."""
    base = {"relationship": "direct", "level": "family", "publisher": "NIST"}
    if record["kind"] == "function":
        return {**base, "status": "not_applicable", "families": []}, [
            "CPRT publishes informative references for categories and "
            f"subcategories, not for functions. Look up a category under "
            f"{record['id']} instead."
        ]
    if not record["references"]:
        return {**base, "status": "none_published", "families": []}, [
            f"NIST publishes no SP 800-53 informative reference for {record['id']} "
            "in CPRT. That is a gap in the published mapping, not a statement "
            "that no control applies."
        ]

    # Every CSF 2.0 reference targets one SP 800-53 document. Report the
    # release it names, and whether the same families exist in the newest
    # release the store holds.
    target_doc = record["references"][0]["target_doc"]
    target_release = store.release_for_document(target_doc)
    newest = store.default_release()
    titles = store.family_titles(target_release) if target_release else {}
    families = [
        {"id": ref["target_id"], "title": titles.get(ref["target_id"])}
        for ref in record["references"]
        if ref["target_doc"] == target_doc
    ]
    result = {
        **base,
        "status": "published",
        "target_document": target_doc,
        "target_release": target_release,
        "families": families,
    }
    notes = [FAMILY_NOTE]
    unknown = [f["id"] for f in families if f["id"] not in titles]
    if unknown:
        notes.append(
            f"Not a family in SP 800-53 release {target_release}: "
            f"{', '.join(unknown)}. Reported as published, without a title."
        )
    if target_release and target_release != newest:
        newest_titles = store.family_titles(newest)
        missing = [f["id"] for f in families if f["id"] not in newest_titles]
        if missing:
            notes.append(
                f"References are published against SP 800-53 release "
                f"{target_release}. Not a family in release {newest}: "
                f"{', '.join(missing)}."
            )
        else:
            result["interpreted_against"] = newest
            notes.append(
                f"References are published against SP 800-53 release "
                f"{target_release}. The same families exist in release {newest}, "
                "so they can be read against it; control level text may differ "
                "between the releases."
            )
    return result, notes
