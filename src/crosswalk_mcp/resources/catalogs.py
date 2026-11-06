"""Reference lists a client can read without a tool call.

These are the outlines a model needs to pick good identifiers: the SP 800-53
families, the CSF 2.0 functions and categories, and the FedRAMP KSI themes.
Each is small, static for a given snapshot, and carries the snapshot hash.
"""

from __future__ import annotations

import json

from fastmcp import FastMCP

from crosswalk_mcp.models import LATEST_RELEASE
from crosswalk_mcp.tools.common import get_store, snapshot_provenance


def families() -> dict:
    """SP 800-53 families with titles and control counts, per release."""
    store = get_store()
    with store.lock:
        releases = {}
        for release in store.releases():
            rows = store.conn.execute(
                "SELECT f.id, f.title, "
                "(SELECT count(*) FROM controls c WHERE c.release = f.release "
                " AND c.family = f.id AND c.withdrawn = 0) AS active_controls "
                "FROM families f WHERE f.release = ? ORDER BY f.id",
                (release["release"],),
            ).fetchall()
            releases[release["release"]] = [dict(row) for row in rows]
        provenance = snapshot_provenance(store)
    return {
        "default_release": LATEST_RELEASE.value,
        "families_by_release": releases,
        "provenance": provenance,
    }


def csf_outline() -> dict:
    """CSF 2.0 functions and their active categories, in published order."""
    store = get_store()
    with store.lock:
        rows = store.conn.execute(
            "SELECT id, kind, parent_id, title, text FROM csf_elements "
            "WHERE legacy = 0 AND kind IN ('function', 'category') ORDER BY sort_key"
        ).fetchall()
        provenance = snapshot_provenance(store)
    functions: list[dict] = []
    by_id: dict[str, dict] = {}
    for row in rows:
        if row["kind"] == "function":
            entry = {
                "id": row["id"],
                "title": row["title"],
                "text": row["text"],
                "categories": [],
            }
            functions.append(entry)
            by_id[row["id"]] = entry
        else:
            by_id[row["parent_id"]]["categories"].append(
                {"id": row["id"], "title": row["title"], "text": row["text"]}
            )
    return {"functions": functions, "provenance": provenance}


def ksi_themes() -> dict:
    """FedRAMP KSI themes with their indicator ids and names."""
    store = get_store()
    with store.lock:
        rows = store.conn.execute(
            "SELECT t.id AS theme_id, t.name AS theme_name, t.status, "
            "i.id, i.name FROM fedramp_themes t "
            "JOIN fedramp_indicators i ON i.theme_id = t.id "
            "ORDER BY t.position, i.position"
        ).fetchall()
        provenance = snapshot_provenance(store)
    themes: list[dict] = []
    by_id: dict[str, dict] = {}
    for row in rows:
        theme = by_id.get(row["theme_id"])
        if theme is None:
            theme = by_id[row["theme_id"]] = {
                "id": row["theme_id"],
                "name": row["theme_name"],
                "status": row["status"],
                "indicators": [],
            }
            themes.append(theme)
        theme["indicators"].append({"id": row["id"], "name": row["name"]})
    return {"themes": themes, "provenance": provenance}


def register(mcp: FastMCP) -> None:
    @mcp.resource("crosswalk://families", mime_type="application/json")
    def families_resource() -> str:
        """SP 800-53 family ids and titles for each release, as JSON."""
        return json.dumps(families(), indent=2)

    @mcp.resource("crosswalk://csf-outline", mime_type="application/json")
    def csf_outline_resource() -> str:
        """CSF 2.0 functions and categories (active only), as JSON."""
        return json.dumps(csf_outline(), indent=2)

    @mcp.resource("crosswalk://ksi-themes", mime_type="application/json")
    def ksi_themes_resource() -> str:
        """FedRAMP KSI themes and the indicators in each, as JSON."""
        return json.dumps(ksi_themes(), indent=2)
