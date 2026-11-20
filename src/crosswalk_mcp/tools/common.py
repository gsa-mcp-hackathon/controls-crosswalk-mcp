"""Shared pieces for the tools: store access, provenance, and errors.

Every tool result carries a `provenance` block built here, so a reader can
trace an answer to the exact source bytes and to the page NIST publishes.
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastmcp.exceptions import ToolError

from crosswalk_mcp.ids import InvalidIdentifier, normalize_control_id
from crosswalk_mcp.models import LATEST_RELEASE, Release
from crosswalk_mcp.sources import SOURCES_BY_KEY
from crosswalk_mcp.store import Store, StoreError, db_path, open_store

# The CPRT catalog page for one element of a framework version.
# https://csrc.nist.gov/projects/cprt
CPRT_ELEMENT_URL = (
    "https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/"
    "{doc}/home?element={element}"
)

_store: Store | None = None
_store_path: Path | None = None
_store_lock = threading.Lock()


def configure_store(path: Path | None) -> None:
    """Point the tools at a store file. Tests use this; the server uses the
    default path from settings."""
    global _store, _store_path
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = None
        _store_path = path


def get_store() -> Store:
    """The shared read only store, opened on first use."""
    global _store
    with _store_lock:
        if _store is None:
            try:
                _store = open_store(_store_path)
            except StoreError as exc:
                raise ToolError(
                    f"The data store is not available: {exc} "
                    "The operator must build it before this server can answer."
                ) from None
        return _store


def store_ready() -> bool:
    """True when the store file exists. Cheap enough for a health check."""
    return (_store_path or db_path()).exists()


def resolve_release(release: Release | None) -> str:
    return (release or LATEST_RELEASE).value


def resolve_control_id(raw: str) -> str:
    """Canonical control id, or a ToolError that shows the accepted spellings."""
    try:
        return normalize_control_id(raw)
    except InvalidIdentifier:
        raise ToolError(
            f"'{raw}' is not an SP 800-53 control id. Use the family letters, "
            "a number, and an optional enhancement, for example AC-2, AC-2(3), "
            "ac-02.03, or AC-02(03). Use controls_search to find a control by "
            "keyword."
        ) from None


def snapshot_provenance(store: Store) -> dict:
    """The part of provenance that is the same for every result."""
    meta = store.meta()
    return {
        "snapshot_hash": meta["manifest_hash"],
        "snapshot_as_of": meta["manifest_written_at"],
        "store_built_at": meta["built_at"],
    }


def source_record(store: Store, source_key: str) -> dict:
    """One source as the status tool describes it, with its file hash."""
    recorded = next(s for s in store.meta()["sources"] if s["key"] == source_key)
    source = SOURCES_BY_KEY[source_key]
    return {
        "key": source_key,
        "description": source.description,
        "publisher": source.publisher,
        "url": source.url,
        "pin": source.pin or None,
        "sha256": recorded["sha256"],
    }


def release_provenance(store: Store, release: str) -> dict:
    """Provenance for one 800-53 release: snapshot plus the source file."""
    release_row = next(r for r in store.releases() if r["release"] == release)
    return {
        **snapshot_provenance(store),
        "release": release,
        "source": source_record(store, release_row["source_key"]),
    }


def resolve_family(store: Store, family: str | None, release: str) -> str | None:
    """Upper case two letter family id, or a ToolError listing the families."""
    if family is None:
        return None
    wanted = family.strip().upper()
    with store.lock:
        rows = store.conn.execute(
            "SELECT id, title FROM families WHERE release = ? ORDER BY id", (release,)
        ).fetchall()
    known = {row["id"]: row["title"] for row in rows}
    if wanted not in known:
        listing = ", ".join(f"{k} ({v.title()})" for k, v in known.items())
        raise ToolError(
            f"'{family}' is not an SP 800-53 family. Use one of: {listing}."
        )
    return wanted


def cprt_citation(store: Store, release: str, cprt_id: str, title: str) -> dict:
    release_row = next(r for r in store.releases() if r["release"] == release)
    return {
        "text": f"NIST SP 800-53 Rev. 5 release {release}, {cprt_id} {title}",
        "url": CPRT_ELEMENT_URL.format(
            doc=release_row["doc_identifier"], element=cprt_id
        ),
    }


def csf_citation(document: dict, record: dict) -> dict:
    """Cite one CSF element on the CPRT catalog page. record needs kind,
    id, and title; document is the store's csf_documents row."""
    label = f"{record['kind']} {record['id']}"
    if record["title"]:
        label += f" {record['title']}"
    return {
        "text": f"NIST Cybersecurity Framework (CSF) 2.0, {label}",
        "url": CPRT_ELEMENT_URL.format(
            doc=document["doc_identifier"], element=record["id"]
        ),
    }


def ksi_citation(document: dict, url: str, record: dict) -> dict:
    """Cite a KSI theme or indicator by the pinned file and the JSON path of
    the record inside it. record is a theme (short_name) or an indicator
    (theme_id) row; document is the store's fedramp_documents row."""
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
