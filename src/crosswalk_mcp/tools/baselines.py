"""Baseline tools: list an SP 800-53B baseline, or check memberships.

Membership comes from the NIST OSCAL resolved baseline catalogs, pinned to
one commit of usnistgov/oscal-content. That is a published relationship, so
every membership is labeled "direct".
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from crosswalk_mcp.models import LATEST_RELEASE, Baseline, PaginationParams
from crosswalk_mcp.store import BASELINES
from crosswalk_mcp.tools.common import (
    get_store,
    resolve_control_id,
    resolve_family,
    snapshot_provenance,
    source_record,
)

MAX_MEMBERSHIP_IDS = 50


def _baseline_record(row: dict) -> dict:
    return {
        "baseline": row["baseline"],
        "title_as_published": row["title"],
        "catalog_version": row["version"],
        "oscal_version": row["oscal_version"],
        "last_modified": row["last_modified"],
        "member_count": row["member_count"],
    }


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="controls_get_baseline",
        annotations={
            "title": "List an SP 800-53B baseline",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def controls_get_baseline(
        baseline: Annotated[
            Baseline,
            Field(description="Which baseline: low, moderate, high, or privacy."),
        ],
        family: Annotated[
            str | None,
            Field(
                max_length=2,
                description="Limit to one family by its two letters, such as AC.",
            ),
        ] = None,
        pagination: PaginationParams | None = None,
    ) -> dict:
        """List the controls and enhancements an SP 800-53B baseline selects.

        Returns the baseline's published metadata and one page of members in
        catalog order. Use the family filter to keep the list short. This is
        the baseline as NIST publishes it, not a tailored or agency overlay.
        """
        store = get_store()
        family_key = resolve_family(store, family, LATEST_RELEASE.value)
        page = pagination or PaginationParams()
        with store.lock:
            row = next(b for b in store.baselines() if b["baseline"] == baseline.value)
            members = store.baseline_members(baseline.value, family_key)
        window = members[page.offset : page.offset + page.limit]
        next_offset = page.offset + len(window)
        notes = []
        if row["version"] and row["version"] not in row["title"]:
            notes.append(
                "The published catalog title names a different release than its "
                "version field. Both are reported as published."
            )
        return {
            "baseline": _baseline_record(row),
            "filters": {"family": family_key},
            "relationship": "direct",
            "total": len(members),
            "count": len(window),
            "offset": page.offset,
            "has_more": next_offset < len(members),
            "next_offset": next_offset if next_offset < len(members) else None,
            "members": window,
            "notes": notes,
            "provenance": {
                **snapshot_provenance(store),
                "source": source_record(store, row["source_key"]),
            },
        }

    @mcp.tool(
        name="controls_baseline_membership",
        annotations={
            "title": "Which baselines include these controls",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def controls_baseline_membership(
        control_ids: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=MAX_MEMBERSHIP_IDS,
                description=(
                    "Control or enhancement ids in any common spelling, "
                    f"up to {MAX_MEMBERSHIP_IDS} at a time."
                ),
            ),
        ],
    ) -> dict:
        """Report which SP 800-53B baselines (low, moderate, high, privacy)
        select each of the given controls.

        An empty list means the control is in no baseline, which is common
        for enhancements and for withdrawn controls. Membership is read from
        the published OSCAL baselines and labeled direct.
        """
        store = get_store()
        wanted = [resolve_control_id(raw) for raw in control_ids]
        if len(set(wanted)) != len(wanted):
            raise ToolError("control_ids contains the same control more than once.")
        with store.lock:
            membership = store.membership(wanted)
            rows = store.conn.execute(
                "SELECT id, title, withdrawn FROM controls WHERE release = ? "
                f"AND id IN ({', '.join('?' for _ in wanted)})",
                [LATEST_RELEASE.value, *wanted],
            ).fetchall()
            baseline_rows = store.baselines()
        known = {row["id"]: row for row in rows}
        controls = []
        for control_id in wanted:
            row = known.get(control_id)
            controls.append(
                {
                    "id": control_id,
                    "found": row is not None,
                    "title": row["title"] if row else None,
                    "withdrawn": bool(row["withdrawn"]) if row else None,
                    "baselines": membership[control_id],
                }
            )
        missing = [c["id"] for c in controls if not c["found"]]
        notes = []
        if missing:
            notes.append(
                f"Not in SP 800-53 release {LATEST_RELEASE.value}: "
                f"{', '.join(missing)}. Check the id with controls_get_control."
            )
        return {
            "relationship": "direct",
            "catalog_release": LATEST_RELEASE.value,
            "controls": controls,
            "notes": notes,
            "provenance": {
                **snapshot_provenance(store),
                "sources": [
                    source_record(store, source_key) for _, source_key in BASELINES
                ],
                "baselines": [_baseline_record(row) for row in baseline_rows],
            },
        }
