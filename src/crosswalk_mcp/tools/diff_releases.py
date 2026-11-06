"""controls_diff_releases: what changed between two SP 800-53 releases.

Three views share one tool. With a control id it reports the exact text
changes for that control. With a family it lists the controls in that
family that were added, removed, or changed. With neither it summarizes
the whole catalog. All three compare the published CPRT exports held in the
store, so the answer is a comparison of NIST text, not an interpretation.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from crosswalk_mcp.diff import diff_controls
from crosswalk_mcp.models import PaginationParams, Release
from crosswalk_mcp.tools.common import (
    cprt_citation,
    get_store,
    resolve_control_id,
    resolve_family,
    snapshot_provenance,
    source_record,
)

CATALOG_NOTE = (
    "Call again with control_id to see the exact wording changes for one "
    "control. A control whose only changed section is relations usually "
    "gained a link to a control that was added in the newer release."
)
TEXT_NOTE = (
    "Discussion and assessment method changes are shown as before and after "
    "excerpts with a few words of context. Use controls_get_control with the "
    "release parameter to read either full text."
)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="controls_diff_releases",
        annotations={
            "title": "Compare SP 800-53 releases",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def controls_diff_releases(
        control_id: Annotated[
            str | None,
            Field(
                description=(
                    "One control or enhancement to compare in detail, in any "
                    "common spelling such as SI-7(12) or si-7.12. Leave unset "
                    "to summarize a family or the whole catalog."
                )
            ),
        ] = None,
        family: Annotated[
            str | None,
            Field(
                max_length=2,
                description=(
                    "Summarize one family by its two letters, such as SA. "
                    "Cannot be combined with control_id."
                ),
            ),
        ] = None,
        from_release: Annotated[
            Release | None,
            Field(description="Older release. Defaults to 5.1.1."),
        ] = None,
        to_release: Annotated[
            Release | None,
            Field(description="Newer release. Defaults to 5.2.0."),
        ] = None,
        pagination: PaginationParams | None = None,
    ) -> dict:
        """Report what changed in SP 800-53 between two releases.

        For one control: the title, statement items, discussion, parameters,
        assessment objectives and methods, references, related controls, and
        withdrawal status that differ, with the old and new wording. For a
        family or the whole catalog: which controls were added, removed, or
        changed, and which sections changed in each. The comparison is made
        between the NIST CPRT exports of both releases, as published.
        """
        store = get_store()
        if control_id is not None and family is not None:
            raise ToolError(
                "Set control_id or family, not both. Use family to list the "
                "changed controls, then control_id to see one in detail."
            )
        older, newer = _resolve_pair(store, from_release, to_release)
        provenance = _provenance(store, older, newer)

        if control_id is not None:
            wanted = resolve_control_id(control_id)
            return _control_view(store, wanted, older, newer, provenance)

        family_key = resolve_family(store, family, newer)
        page = pagination or PaginationParams()
        with store.lock:
            catalog = store.catalog_diff(older, newer)

        def in_scope(item: dict) -> bool:
            return family_key is None or item["id"].startswith(f"{family_key}-")

        added = [c for c in catalog["added"] if in_scope(c)]
        removed = [c for c in catalog["removed"] if in_scope(c)]
        changed = [c for c in catalog["changed"] if in_scope(c)]
        unchanged = catalog["unchanged"]
        if family_key is not None:
            with store.lock:
                total_in_family = store.conn.execute(
                    "SELECT count(*) FROM controls WHERE release = ? AND family = ?",
                    (newer, family_key),
                ).fetchone()[0]
            unchanged = total_in_family - len(added) - len(changed)

        by_section: dict[str, int] = {}
        for item in changed:
            for section in item["changed_sections"]:
                by_section[section] = by_section.get(section, 0) + 1

        window = changed[page.offset : page.offset + page.limit]
        next_offset = page.offset + len(window)
        return {
            "scope": {"control_id": None, "family": family_key},
            "from_release": older,
            "to_release": newer,
            "summary": {
                "added": len(added),
                "removed": len(removed),
                "changed": len(changed),
                "unchanged": unchanged,
                "changed_by_section": by_section,
            },
            "added": added,
            "removed": removed,
            "changed": {
                "total": len(changed),
                "count": len(window),
                "offset": page.offset,
                "has_more": next_offset < len(changed),
                "next_offset": next_offset if next_offset < len(changed) else None,
                "items": window,
            },
            "notes": [CATALOG_NOTE],
            "provenance": provenance,
        }


def _resolve_pair(store, from_release, to_release) -> tuple[str, str]:
    """Older and newer release keys, defaulting to the oldest and newest held."""
    held = [r["release"] for r in store.releases()]  # newest first
    older = from_release.value if from_release else held[-1]
    newer = to_release.value if to_release else held[0]
    if older == newer:
        raise ToolError(
            f"from_release and to_release are both {older}. Pick two different "
            f"releases from: {', '.join(held)}."
        )
    if held.index(older) < held.index(newer):
        raise ToolError(
            f"from_release {older} is newer than to_release {newer}. Swap them "
            "so the comparison reads from older to newer."
        )
    return older, newer


def _provenance(store, older: str, newer: str) -> dict:
    def one(release: str) -> dict:
        row = next(r for r in store.releases() if r["release"] == release)
        return {"release": release, "source": source_record(store, row["source_key"])}

    return {**snapshot_provenance(store), "from": one(older), "to": one(newer)}


def _control_view(store, control_id: str, older: str, newer: str, provenance) -> dict:
    with store.lock:
        before = store.get_control(control_id, older)
        after = store.get_control(control_id, newer)
    if before is None and after is None:
        raise ToolError(
            f"{control_id} is not in SP 800-53 release {older} or {newer}. Check "
            "the id, or use controls_search to find the control by keyword."
        )
    present = after or before
    citations = {}
    if before is not None:
        citations["from"] = cprt_citation(
            store, older, before["cprt_id"], before["title"]
        )
    if after is not None:
        citations["to"] = cprt_citation(store, newer, after["cprt_id"], after["title"])

    notes = []
    if before is None:
        status, changes = "added", {}
        notes.append(f"{control_id} is new in release {newer}.")
    elif after is None:
        status, changes = "removed", {}
        notes.append(f"{control_id} is not present in release {newer}.")
    else:
        changes = diff_controls(before, after)
        status = "changed" if changes else "unchanged"
        if changes and ("discussion" in changes or "assessment_methods" in changes):
            notes.append(TEXT_NOTE)
        if not changes:
            notes.append(
                f"The published text of {control_id} is the same in {older} and "
                f"{newer}, apart from whitespace."
            )
    return {
        "scope": {"control_id": control_id, "family": None},
        "from_release": older,
        "to_release": newer,
        "control": {
            "id": present["id"],
            "title": present["title"],
            "parent_id": present["parent_id"],
            "withdrawn": present["withdrawn"],
        },
        "status": status,
        "changed_sections": list(changes),
        "changes": changes,
        "notes": notes,
        "provenance": {**provenance, "citations": citations},
    }
