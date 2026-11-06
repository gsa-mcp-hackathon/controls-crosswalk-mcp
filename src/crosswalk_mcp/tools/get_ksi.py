"""controls_get_ksi: FedRAMP Key Security Indicator themes and indicators.

FedRAMP lists SP 800-53 controls under each indicator and calls them
"Related SP 800-53 Controls". This tool returns that list as published. It
is not a coverage or equivalence rating, and the file names no SP 800-53
release, so the result says "unspecified" for the catalog release and only
resolves titles against the newest release the store holds.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from crosswalk_mcp.ids import InvalidIdentifier, normalize_ksi_id
from crosswalk_mcp.models import LATEST_RELEASE
from crosswalk_mcp.store import FEDRAMP_SOURCE, Store
from crosswalk_mcp.tools.common import get_store, snapshot_provenance, source_record

RELATED_NOTE = (
    "FedRAMP calls this list 'Related SP 800-53 Controls'. It is published "
    "without naming an SP 800-53 release and is not a coverage or equivalence "
    "rating. Titles, withdrawal flags, and baselines are resolved against "
    f"release {LATEST_RELEASE.value}."
)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="controls_get_ksi",
        annotations={
            "title": "Get a FedRAMP Key Security Indicator",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def controls_get_ksi(
        ksi_id: Annotated[
            str | None,
            Field(
                description=(
                    "A KSI theme such as KSI-CNA, or an indicator such as "
                    "KSI-CNA-EIS. Leave unset to list every theme."
                )
            ),
        ] = None,
    ) -> dict:
        """Return FedRAMP Key Security Indicators (KSIs) from the consolidated
        rules file, with the SP 800-53 controls FedRAMP relates to each one.

        With no id, lists the ten themes. With a theme id, lists that theme's
        indicators. With an indicator id, returns its statement (or one
        statement per authorization class when it varies), the FedRAMP
        definitions of the terms it uses, its change history, and the
        related controls with their titles and SP 800-53B baselines. The
        control list is exactly what FedRAMP publishes; this tool never
        states that an indicator or control is satisfied.
        """
        store = get_store()
        wanted = _resolve_ksi_id(ksi_id)
        with store.lock:
            document = store.fedramp_document()
            provenance = {
                **snapshot_provenance(store),
                "source": source_record(store, FEDRAMP_SOURCE),
                "document": document_record(document),
            }
            if wanted is None:
                return {
                    "themes": [_theme_record(t) for t in store.ksi_themes()],
                    "notes": [
                        "Call again with a theme id to list its indicators, or "
                        "with an indicator id for its statement and controls."
                    ],
                    "provenance": provenance,
                }
            if wanted.count("-") == 1:
                return _theme_view(store, wanted, document, provenance)
            return _indicator_view(store, wanted, document, provenance)


def _resolve_ksi_id(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    try:
        return normalize_ksi_id(raw)
    except InvalidIdentifier:
        raise ToolError(
            f"'{raw}' is not a FedRAMP KSI identifier. Use a theme such as "
            "KSI-CNA or an indicator such as KSI-CNA-EIS, or call with no id "
            "to list the themes."
        ) from None


def document_record(document: dict) -> dict:
    return {
        "title": document["title"],
        "version": document["version"],
        "last_updated": document["last_updated"],
    }


def _theme_record(theme: dict) -> dict:
    return {
        "id": theme["id"],
        "name": theme["name"],
        "status": theme["status"],
        "indicator_count": theme["indicator_count"],
    }


def _theme_view(store: Store, theme_id: str, document: dict, provenance: dict):
    theme = store.get_ksi_theme(theme_id)
    if theme is None:
        known = ", ".join(t["id"] for t in store.ksi_themes())
        raise ToolError(
            f"{theme_id} is not a KSI theme in the FedRAMP rules this server "
            f"holds. Themes: {known}."
        )
    return {
        "theme": {
            "id": theme["id"],
            "name": theme["name"],
            "status": theme["status"],
            "indicators": theme["indicators"],
        },
        "notes": [
            "Call again with an indicator id for its full statement, terms, "
            "and related controls."
        ],
        "provenance": {
            **provenance,
            "citation": _citation(document, provenance["source"]["url"], theme),
        },
    }


def _indicator_view(store: Store, indicator_id: str, document: dict, provenance):
    record = store.get_ksi(indicator_id)
    if record is None:
        theme_id = indicator_id.rsplit("-", 1)[0]
        hint = (
            f"Call with {theme_id} to list that theme's indicators."
            if store.get_ksi_theme(theme_id)
            else "Call with no id to list the themes."
        )
        raise ToolError(
            f"{indicator_id} is not a KSI in the FedRAMP rules this server holds. "
            + hint
        )

    control_ids = [c["id"] for c in record["controls"]]
    known = {}
    if control_ids:
        rows = store.conn.execute(
            "SELECT id, title, withdrawn FROM controls WHERE release = ? "
            f"AND id IN ({', '.join('?' for _ in control_ids)})",
            [LATEST_RELEASE.value, *control_ids],
        ).fetchall()
        known = {row["id"]: row for row in rows}
    membership = store.membership(control_ids)
    controls = []
    for control in record["controls"]:
        row = known.get(control["id"])
        controls.append(
            {
                "id": control["id"],
                "oscal_id": control["oscal_id"],
                "found": row is not None,
                "title": row["title"] if row else None,
                "withdrawn": bool(row["withdrawn"]) if row else None,
                "baselines": membership[control["id"]],
            }
        )

    notes = []
    if record["classes"]:
        notes.append(
            f"{indicator_id} has a different statement for each FedRAMP "
            "authorization class. All published class statements are shown."
        )
    if controls:
        notes.append(RELATED_NOTE)
    else:
        notes.append(f"FedRAMP lists no related SP 800-53 controls for {indicator_id}.")
    missing = [c["id"] for c in controls if not c["found"]]
    if missing:
        notes.append(
            f"Not in SP 800-53 release {LATEST_RELEASE.value}: {', '.join(missing)}. "
            "Reported as published, without a title."
        )
    withdrawn = [c["id"] for c in controls if c["withdrawn"]]
    if withdrawn:
        notes.append(
            f"Withdrawn in SP 800-53 release {LATEST_RELEASE.value}: "
            f"{', '.join(withdrawn)}. Use controls_get_control to see where "
            "each one moved."
        )

    return {
        "indicator": {
            "id": record["id"],
            "theme": {"id": record["theme_id"], "name": record["theme_name"]},
            "name": record["name"],
            "statement": record["statement"],
            "statements_by_class": (
                {c["class"]: c["statement"] for c in record["classes"]}
                if record["classes"]
                else None
            ),
            "terms": record["terms"],
            "updated": record["updated"],
        },
        "related_controls": {
            "relationship": "direct",
            "publisher": "FedRAMP",
            "label_as_published": "Related SP 800-53 Controls",
            "catalog_release": "unspecified",
            "resolved_against": LATEST_RELEASE.value,
            "status": "published" if controls else "none_published",
            "count": len(controls),
            "controls": controls,
        },
        "notes": notes,
        "provenance": {
            **provenance,
            "citation": _citation(document, provenance["source"]["url"], record),
        },
    }


def _citation(document: dict, url: str, record: dict) -> dict:
    """Cite the pinned file and the JSON path of the record inside it."""
    if "theme_id" in record:
        path = (
            f"KSI.{record['theme_id'].removeprefix('KSI-')}.indicators.{record['id']}"
        )
    else:
        path = f"KSI.{record['short_name']}"
    return {
        "text": (
            f"{document['title']}, version {document['version']}, "
            f"{record['id']} {record['name']}"
        ),
        "url": url,
        "json_path": path,
    }
