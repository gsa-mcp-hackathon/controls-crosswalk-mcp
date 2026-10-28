"""controls_data_status: what data this server holds and where it came from."""

from __future__ import annotations

from fastmcp import FastMCP

from crosswalk_mcp.sources import SOURCES
from crosswalk_mcp.store import SCHEMA_VERSION
from crosswalk_mcp.tools.common import get_store, snapshot_provenance

SCOPE_NOTE = (
    "Unofficial. Not affiliated with or endorsed by NIST, GSA, or FedRAMP. "
    "Text is reproduced from public NIST and FedRAMP sources without change. "
    "This server reports published relationships; it never states that a "
    "requirement is satisfied."
)


def data_status() -> dict:
    """The status record, shared by the tool and the resource."""
    store = get_store()
    with store.lock:
        meta = store.meta()
        releases = store.releases()
        counts = {
            r["release"]: store.conn.execute(
                "SELECT count(*) FROM controls WHERE release = ?", (r["release"],)
            ).fetchone()[0]
            for r in releases
        }
    recorded = {s["key"]: s for s in meta["sources"]}
    sources = []
    for source in SOURCES:
        entry = recorded.get(source.key, {})
        sources.append(
            {
                "key": source.key,
                "description": source.description,
                "publisher": source.publisher,
                "url": source.url,
                "pin": source.pin or None,
                "sha256": entry.get("sha256"),
            }
        )
    return {
        "datasets": [
            {
                "dataset": "SP 800-53 Rev. 5",
                "release": r["release"],
                "source_key": r["source_key"],
                "controls_and_enhancements": counts[r["release"]],
            }
            for r in releases
        ],
        "sources": sources,
        "store_schema_version": SCHEMA_VERSION,
        "scope": SCOPE_NOTE,
        "provenance": snapshot_provenance(store),
    }


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="controls_data_status",
        annotations={
            "title": "Data status and provenance",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def controls_data_status() -> dict:
        """Report which datasets and releases this server holds, the snapshot
        hash that every other result refers to, and the pinned source URLs
        with their file hashes. Call this to learn how current the data is
        before relying on an answer.
        """
        return data_status()
