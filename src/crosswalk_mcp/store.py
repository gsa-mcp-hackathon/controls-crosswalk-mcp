"""The SQLite store the tools read from, and the build step that fills it.

The store is built from the files in data/raw by an operator, never at
request time. It records the manifest hash of the snapshot it was built
from, and every tool result reports that hash.

    uv run python -m crosswalk_mcp.store build
    uv run python -m crosswalk_mcp.store status

Full text search uses the SQLite FTS5 extension, which ships with the
Python builds that uv installs. https://www.sqlite.org/fts5.html
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from crosswalk_mcp.config import settings
from crosswalk_mcp.diff import diff_catalog
from crosswalk_mcp.loaders import csf, oscal_baselines, sp800_53
from crosswalk_mcp.snapshot import SnapshotError, raw_dir, read_manifest, verify

DB_NAME = "crosswalk.sqlite"
SCHEMA_VERSION = 3

# Which raw source feeds which 800-53 release. The newest release is first,
# which makes it the default for lookups.
SP800_53_RELEASES: tuple[tuple[str, str], ...] = (
    ("5.2.0", "sp800_53_5_2_0"),
    ("5.1.1", "sp800_53_5_1_1"),
)

# The four SP 800-53B baselines and the raw source that holds each.
BASELINES: tuple[tuple[str, str], ...] = (
    ("low", "baseline_low"),
    ("moderate", "baseline_moderate"),
    ("high", "baseline_high"),
    ("privacy", "baseline_privacy"),
)

# The raw source that holds the CSF 2.0 core, and the release it is.
CSF_SOURCE = "csf_2_0_0"
CSF_RELEASE = "2.0"

SCHEMA = """
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE releases (
    release TEXT PRIMARY KEY,
    doc_identifier TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    website TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_sha256 TEXT NOT NULL
);

CREATE TABLE families (
    release TEXT NOT NULL,
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    PRIMARY KEY (release, id)
);

-- One row per control or enhancement. id is the canonical form, AC-2(3).
CREATE TABLE controls (
    release TEXT NOT NULL,
    id TEXT NOT NULL,
    cprt_id TEXT NOT NULL,
    oscal_id TEXT NOT NULL,
    family TEXT NOT NULL,
    parent_id TEXT,
    title TEXT NOT NULL,
    sort_key TEXT NOT NULL,
    withdrawn INTEGER NOT NULL,
    withdraw_reason TEXT,
    statement_text TEXT NOT NULL,
    discussion TEXT NOT NULL,
    privacy_baseline INTEGER NOT NULL,
    PRIMARY KEY (release, id)
);
CREATE INDEX controls_parent ON controls (release, parent_id);
CREATE INDEX controls_family ON controls (release, family, sort_key);

-- The statement tree. Root rows have no parent and usually no label.
CREATE TABLE statements (
    release TEXT NOT NULL,
    control_id TEXT NOT NULL,
    id TEXT NOT NULL,
    parent_id TEXT,
    label TEXT,
    text TEXT NOT NULL,
    depth INTEGER NOT NULL,
    position INTEGER NOT NULL
);
CREATE INDEX statements_control ON statements (release, control_id, position);

-- Assessment objectives (SP 800-53A determination statements).
CREATE TABLE objectives (
    release TEXT NOT NULL,
    control_id TEXT NOT NULL,
    id TEXT NOT NULL,
    statement_id TEXT NOT NULL,
    text TEXT NOT NULL,
    parameter_ids TEXT NOT NULL,
    position INTEGER NOT NULL
);
CREATE INDEX objectives_control ON objectives (release, control_id, position);

-- Organization defined parameters.
CREATE TABLE parameters (
    release TEXT NOT NULL,
    control_id TEXT NOT NULL,
    id TEXT NOT NULL,
    label TEXT NOT NULL,
    guideline TEXT NOT NULL,
    kind TEXT NOT NULL,
    statement TEXT,
    choices TEXT
);
CREATE INDEX parameters_control ON parameters (release, control_id);

CREATE TABLE assessment_methods (
    release TEXT NOT NULL,
    control_id TEXT NOT NULL,
    method TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX assessment_methods_control ON assessment_methods (release, control_id);

CREATE TABLE control_references (
    release TEXT NOT NULL,
    control_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL
);
CREATE INDEX control_references_control ON control_references (release, control_id);

-- kind is related, incorporated_into, or moved_to, exactly as CPRT labels it.
CREATE TABLE control_relations (
    release TEXT NOT NULL,
    source_id TEXT NOT NULL,
    dest_id TEXT NOT NULL,
    kind TEXT NOT NULL
);
CREATE INDEX control_relations_source ON control_relations (release, source_id);
CREATE INDEX control_relations_dest ON control_relations (release, dest_id);

-- Baseline membership as CPRT states it per control. The OSCAL resolved
-- baselines are loaded separately and are the authoritative 800-53B view.
CREATE TABLE cprt_baselines (
    release TEXT NOT NULL,
    control_id TEXT NOT NULL,
    baseline TEXT NOT NULL,
    PRIMARY KEY (release, control_id, baseline)
);

-- SP 800-53B baselines from the OSCAL resolved catalogs.
CREATE TABLE baselines (
    baseline TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    oscal_version TEXT NOT NULL,
    last_modified TEXT NOT NULL,
    catalog_uuid TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_sha256 TEXT NOT NULL
);

CREATE TABLE baseline_members (
    baseline TEXT NOT NULL,
    control_id TEXT NOT NULL,
    oscal_id TEXT NOT NULL,
    title TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (baseline, control_id)
);
CREATE INDEX baseline_members_control ON baseline_members (control_id);

-- CSF 2.0 from the CPRT export. One document row describes the export.
CREATE TABLE csf_documents (
    doc_identifier TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    website TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_sha256 TEXT NOT NULL
);

-- Functions (GV), categories (GV.OC), and subcategories (GV.OC-01).
-- legacy marks a CSF 1.1 identifier that CSF 2.0 retired; legacy_note is
-- the CPRT text saying where its content went.
CREATE TABLE csf_elements (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    parent_id TEXT,
    function_id TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    sort_key TEXT NOT NULL,
    legacy INTEGER NOT NULL,
    legacy_note TEXT
);
CREATE INDEX csf_elements_parent ON csf_elements (parent_id, sort_key);

CREATE TABLE csf_examples (
    element_id TEXT NOT NULL,
    id TEXT NOT NULL,
    label TEXT NOT NULL,
    text TEXT NOT NULL,
    position INTEGER NOT NULL
);
CREATE INDEX csf_examples_element ON csf_examples (element_id, position);

-- Where a legacy identifier went: incorporated_into or moved_to.
CREATE TABLE csf_relations (
    source_id TEXT NOT NULL,
    dest_id TEXT NOT NULL,
    kind TEXT NOT NULL
);
CREATE INDEX csf_relations_source ON csf_relations (source_id);
CREATE INDEX csf_relations_dest ON csf_relations (dest_id);

-- Informative references as CPRT publishes them: target_doc names the
-- SP 800-53 release and target_id is a family, never a single control.
CREATE TABLE csf_references (
    element_id TEXT NOT NULL,
    target_doc TEXT NOT NULL,
    target_id TEXT NOT NULL
);
CREATE INDEX csf_references_element ON csf_references (element_id);

-- CPRT's first party and third party risk tags on subcategories.
CREATE TABLE csf_tags (
    element_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    label TEXT NOT NULL
);
CREATE INDEX csf_tags_element ON csf_tags (element_id);

CREATE VIRTUAL TABLE controls_fts USING fts5(
    release UNINDEXED,
    id UNINDEXED,
    title,
    statement_text,
    discussion,
    tokenize = 'porter unicode61'
);
"""


class StoreError(RuntimeError):
    """A build or open problem the operator needs to see."""


@dataclass(frozen=True)
class BuildReport:
    path: Path
    manifest_hash: str
    counts: dict[str, int]


def db_path() -> Path:
    return Path(settings.data_dir) / DB_NAME


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _insert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    conn.executemany(sql, [tuple(row[c] for c in columns) for row in rows])


def build(source_dir: Path | None = None, dest: Path | None = None) -> BuildReport:
    """Build the store from the raw files and their manifest.

    Refuses to build if the manifest does not match the files, so the hash
    recorded in the store always describes the bytes that went into it.
    """
    source_dir = source_dir or raw_dir()
    dest = dest or db_path()
    problems = verify(source_dir)
    if problems:
        raise StoreError("snapshot does not verify: " + "; ".join(problems))
    manifest = read_manifest(source_dir)
    by_key = {entry["key"]: entry for entry in manifest["sources"]}

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    partial.unlink(missing_ok=True)
    conn = sqlite3.connect(partial)
    try:
        conn.executescript(SCHEMA)
        for release, source_key in SP800_53_RELEASES:
            entry = by_key[source_key]
            with (source_dir / entry["filename"]).open("rb") as handle:
                payload = json.load(handle)
            rows = sp800_53.load(payload, release, source_key, entry["sha256"])
            _insert(conn, "releases", [rows.release])
            for table in (
                "families",
                "controls",
                "statements",
                "objectives",
                "parameters",
                "assessment_methods",
                "control_references",
                "control_relations",
                "cprt_baselines",
            ):
                _insert(conn, table, getattr(rows, table))
            _insert(
                conn,
                "controls_fts",
                [
                    {
                        "release": c["release"],
                        "id": c["id"],
                        "title": c["title"],
                        "statement_text": c["statement_text"],
                        "discussion": c["discussion"],
                    }
                    for c in rows.controls
                ],
            )

        for baseline, source_key in BASELINES:
            entry = by_key[source_key]
            with (source_dir / entry["filename"]).open("rb") as handle:
                payload = json.load(handle)
            rows = oscal_baselines.load(payload, baseline, source_key, entry["sha256"])
            _insert(conn, "baselines", [rows.baseline])
            _insert(conn, "baseline_members", rows.members)

        entry = by_key[CSF_SOURCE]
        with (source_dir / entry["filename"]).open("rb") as handle:
            payload = json.load(handle)
        csf_rows = csf.load(payload, CSF_SOURCE, entry["sha256"])
        _insert(conn, "csf_documents", [csf_rows.document])
        for table in ("elements", "examples", "relations", "references", "tags"):
            _insert(conn, f"csf_{table}", getattr(csf_rows, table))

        meta = {
            "schema_version": str(SCHEMA_VERSION),
            "manifest_hash": manifest["manifest_hash"],
            "manifest_written_at": manifest["written_at"],
            "built_at": _utcnow(),
            "sources": json.dumps(
                [
                    {k: entry[k] for k in ("key", "url", "pin", "sha256")}
                    for entry in manifest["sources"]
                ]
            ),
        }
        _insert(conn, "meta", [{"key": k, "value": v} for k, v in meta.items()])
        conn.commit()
        counts = _counts(conn)
    finally:
        conn.close()
    partial.replace(dest)
    return BuildReport(
        path=dest, manifest_hash=manifest["manifest_hash"], counts=counts
    )


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        "releases",
        "families",
        "controls",
        "statements",
        "objectives",
        "parameters",
        "assessment_methods",
        "control_references",
        "control_relations",
        "cprt_baselines",
        "baselines",
        "baseline_members",
        "csf_elements",
        "csf_examples",
        "csf_relations",
        "csf_references",
        "csf_tags",
    ]
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


class Store:
    """Read side of the store. One instance can serve many lookups."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        # Tools may run on worker threads. One connection shared under a
        # lock is plenty for a read only store of this size.
        self.lock = threading.Lock()
        self._diff_cache: dict[tuple[str, str], dict] = {}

    def close(self) -> None:
        self.conn.close()

    def meta(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM meta").fetchall()
        meta = {row["key"]: row["value"] for row in rows}
        meta["sources"] = json.loads(meta.get("sources", "[]"))
        return meta

    def releases(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM releases ORDER BY release DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def default_release(self) -> str:
        return SP800_53_RELEASES[0][0]

    def has_release(self, release: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM releases WHERE release = ?", (release,)
        ).fetchone()
        return row is not None

    def get_control(self, control_id: str, release: str) -> dict | None:
        """Everything the store holds about one control, as nested dicts."""
        q = self.conn.execute
        control = q(
            "SELECT * FROM controls WHERE release = ? AND id = ?", (release, control_id)
        ).fetchone()
        if control is None:
            return None
        key = (release, control_id)
        result = dict(control)
        result["withdrawn"] = bool(result["withdrawn"])
        result["privacy_baseline"] = bool(result["privacy_baseline"])
        family = q(
            "SELECT title FROM families WHERE release = ? AND id = ?",
            (release, result["family"]),
        ).fetchone()
        result["family_title"] = family["title"] if family else None

        result["statement"] = _statement_tree(
            q(
                "SELECT id, parent_id, label, text FROM statements "
                "WHERE release = ? AND control_id = ? ORDER BY position",
                key,
            ).fetchall()
        )
        result["objectives"] = [
            {
                "id": row["id"],
                "statement_id": row["statement_id"],
                "text": row["text"],
                "parameter_ids": json.loads(row["parameter_ids"]),
            }
            for row in q(
                "SELECT id, statement_id, text, parameter_ids FROM objectives "
                "WHERE release = ? AND control_id = ? ORDER BY position",
                key,
            ).fetchall()
        ]
        result["parameters"] = [
            {
                "id": row["id"],
                "label": row["label"],
                "guideline": row["guideline"],
                "kind": row["kind"],
                "statement": row["statement"],
                "choices": json.loads(row["choices"]) if row["choices"] else None,
            }
            for row in q(
                "SELECT * FROM parameters WHERE release = ? AND control_id = ? "
                "ORDER BY rowid",
                key,
            ).fetchall()
        ]
        result["assessment_methods"] = {
            row["method"]: row["text"]
            for row in q(
                "SELECT method, text FROM assessment_methods "
                "WHERE release = ? AND control_id = ?",
                key,
            ).fetchall()
        }
        result["references"] = [
            dict(row)
            for row in q(
                "SELECT title, url FROM control_references "
                "WHERE release = ? AND control_id = ? ORDER BY rowid",
                key,
            ).fetchall()
        ]
        relations: dict[str, list[str]] = defaultdict(list)
        for row in q(
            "SELECT dest_id, kind FROM control_relations "
            "WHERE release = ? AND source_id = ? ORDER BY rowid",
            key,
        ).fetchall():
            relations[row["kind"]].append(row["dest_id"])
        result["related"] = relations.get("related", [])
        result["incorporated_into"] = relations.get("incorporated_into", [])
        result["moved_to"] = relations.get("moved_to", [])
        result["enhancements"] = [
            {
                "id": row["id"],
                "title": row["title"],
                "withdrawn": bool(row["withdrawn"]),
            }
            for row in q(
                "SELECT id, title, withdrawn FROM controls "
                "WHERE release = ? AND parent_id = ? ORDER BY sort_key",
                key,
            ).fetchall()
        ]
        result["cprt_baselines"] = [
            row["baseline"]
            for row in q(
                "SELECT baseline FROM cprt_baselines "
                "WHERE release = ? AND control_id = ? ORDER BY rowid",
                key,
            ).fetchall()
        ]
        return result

    def release_records(self, release: str) -> dict[str, dict]:
        """Every control in one release, keyed by id, shaped like get_control.

        Loads each table once instead of once per control, so comparing two
        whole releases stays fast. Family titles, enhancements, and baseline
        flags are left out because the comparison does not use them.
        """
        q = self.conn.execute
        records: dict[str, dict] = {}
        for row in q("SELECT * FROM controls WHERE release = ?", (release,)):
            record = dict(row)
            record["withdrawn"] = bool(record["withdrawn"])
            record["privacy_baseline"] = bool(record["privacy_baseline"])
            record.update(
                statement=[],
                objectives=[],
                parameters=[],
                assessment_methods={},
                references=[],
                related=[],
                incorporated_into=[],
                moved_to=[],
            )
            records[record["id"]] = record

        statements: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in q(
            "SELECT control_id, id, parent_id, label, text FROM statements "
            "WHERE release = ? ORDER BY position",
            (release,),
        ):
            statements[row["control_id"]].append(row)
        for control_id, rows in statements.items():
            records[control_id]["statement"] = _statement_tree(rows)

        for row in q(
            "SELECT control_id, id, statement_id, text, parameter_ids "
            "FROM objectives WHERE release = ? ORDER BY position",
            (release,),
        ):
            records[row["control_id"]]["objectives"].append(
                {
                    "id": row["id"],
                    "statement_id": row["statement_id"],
                    "text": row["text"],
                    "parameter_ids": json.loads(row["parameter_ids"]),
                }
            )
        for row in q(
            "SELECT * FROM parameters WHERE release = ? ORDER BY rowid", (release,)
        ):
            records[row["control_id"]]["parameters"].append(
                {
                    "id": row["id"],
                    "label": row["label"],
                    "guideline": row["guideline"],
                    "kind": row["kind"],
                    "statement": row["statement"],
                    "choices": json.loads(row["choices"]) if row["choices"] else None,
                }
            )
        for row in q(
            "SELECT control_id, method, text FROM assessment_methods WHERE release = ?",
            (release,),
        ):
            records[row["control_id"]]["assessment_methods"][row["method"]] = row[
                "text"
            ]
        for row in q(
            "SELECT control_id, title, url FROM control_references "
            "WHERE release = ? ORDER BY rowid",
            (release,),
        ):
            records[row["control_id"]]["references"].append(
                {"title": row["title"], "url": row["url"]}
            )
        for row in q(
            "SELECT source_id, dest_id, kind FROM control_relations "
            "WHERE release = ? ORDER BY rowid",
            (release,),
        ):
            records[row["source_id"]][row["kind"]].append(row["dest_id"])
        return records

    def catalog_diff(self, from_release: str, to_release: str) -> dict:
        """The catalog comparison from diff.diff_catalog, computed once per
        pair of releases and kept, since the store never changes while open."""
        key = (from_release, to_release)
        if key not in self._diff_cache:
            self._diff_cache[key] = diff_catalog(
                self.release_records(from_release), self.release_records(to_release)
            )
        return self._diff_cache[key]

    def release_for_document(self, doc_identifier: str) -> str | None:
        """The 800-53 release built from a CPRT document such as
        SP_800_53_5_1_1, or None if the store does not hold it. Each release
        is its own document in NIST's data; if a store were built with the
        same document twice, the oldest release wins."""
        row = self.conn.execute(
            "SELECT release FROM releases WHERE doc_identifier = ? "
            "ORDER BY release LIMIT 1",
            (doc_identifier,),
        ).fetchone()
        return row["release"] if row else None

    def family_titles(self, release: str) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT id, title FROM families WHERE release = ? ORDER BY id", (release,)
        ).fetchall()
        return {row["id"]: row["title"] for row in rows}

    def csf_document(self) -> dict:
        return dict(self.conn.execute("SELECT * FROM csf_documents").fetchone())

    def csf_counts(self) -> dict:
        """How many active and legacy identifiers of each kind the store holds."""
        counts: dict[str, dict[str, int]] = {"active": {}, "legacy": {}}
        for row in self.conn.execute(
            "SELECT kind, legacy, count(*) AS n FROM csf_elements GROUP BY kind, legacy"
        ):
            counts["legacy" if row["legacy"] else "active"][row["kind"]] = row["n"]
        return counts

    def get_csf_element(self, csf_id: str) -> dict | None:
        """One function, category, or subcategory with everything attached."""
        q = self.conn.execute
        row = q("SELECT * FROM csf_elements WHERE id = ?", (csf_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["legacy"] = bool(result["legacy"])
        result["examples"] = [
            {"id": r["id"], "label": r["label"], "text": r["text"]}
            for r in q(
                "SELECT id, label, text FROM csf_examples WHERE element_id = ? "
                "ORDER BY position",
                (csf_id,),
            )
        ]
        result["tags"] = [
            {"tag": r["tag"], "label": r["label"]}
            for r in q(
                "SELECT tag, label FROM csf_tags WHERE element_id = ? ORDER BY rowid",
                (csf_id,),
            )
        ]
        result["references"] = [
            {"target_doc": r["target_doc"], "target_id": r["target_id"]}
            for r in q(
                "SELECT target_doc, target_id FROM csf_references "
                "WHERE element_id = ? ORDER BY target_id",
                (csf_id,),
            )
        ]
        relations: dict[str, list[str]] = defaultdict(list)
        for r in q(
            "SELECT dest_id, kind FROM csf_relations WHERE source_id = ? "
            "ORDER BY rowid",
            (csf_id,),
        ):
            relations[r["kind"]].append(r["dest_id"])
        result["incorporated_into"] = relations.get("incorporated_into", [])
        result["moved_to"] = relations.get("moved_to", [])
        result["legacy_sources"] = [
            {"id": r["source_id"], "kind": r["kind"]}
            for r in q(
                "SELECT source_id, kind FROM csf_relations WHERE dest_id = ? "
                "ORDER BY source_id",
                (csf_id,),
            )
        ]
        result["children"] = [
            {
                "id": r["id"],
                "kind": r["kind"],
                "title": r["title"],
                "text": r["text"],
                "legacy": bool(r["legacy"]),
            }
            for r in q(
                "SELECT id, kind, title, text, legacy FROM csf_elements "
                "WHERE parent_id = ? ORDER BY sort_key, id",
                (csf_id,),
            )
        ]
        return result

    def baselines(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT b.*, (SELECT count(*) FROM baseline_members m "
            " WHERE m.baseline = b.baseline) AS member_count FROM baselines b"
        ).fetchall()
        order = [name for name, _ in BASELINES]
        return sorted((dict(r) for r in rows), key=lambda r: order.index(r["baseline"]))

    def baseline_members(self, baseline: str, family: str | None = None) -> list[dict]:
        sql = (
            "SELECT control_id AS id, oscal_id, title FROM baseline_members "
            "WHERE baseline = ?"
        )
        params: list = [baseline]
        if family:
            # Family is the letters before the dash, which the canonical id
            # always starts with.
            sql += " AND control_id LIKE ?"
            params.append(f"{family}-%")
        sql += " ORDER BY position"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def membership(self, control_ids: list[str]) -> dict[str, list[str]]:
        """Which baselines list each of the given controls."""
        result: dict[str, list[str]] = {control_id: [] for control_id in control_ids}
        if not control_ids:
            return result
        marks = ", ".join("?" for _ in control_ids)
        rows = self.conn.execute(
            f"SELECT control_id, baseline FROM baseline_members "
            f"WHERE control_id IN ({marks})",
            control_ids,
        ).fetchall()
        order = [name for name, _ in BASELINES]
        for row in rows:
            result[row["control_id"]].append(row["baseline"])
        for baselines in result.values():
            baselines.sort(key=order.index)
        return result

    def search(
        self,
        query: str,
        release: str,
        family: str | None = None,
        baseline: str | None = None,
        include_withdrawn: bool = False,
        limit: int = 20,
        offset: int = 0,
        any_word: bool = False,
    ) -> tuple[int, list[dict]]:
        """Full text search over titles, statements, and discussion.

        Returns the total number of matches and one page of them, best
        match first. Title matches weigh more than statement matches, which
        weigh more than discussion matches. By default every word must
        match; any_word relaxes that to at least one word.
        """
        match = fts_query(query, any_word=any_word)
        where = ["controls_fts MATCH ?", "controls_fts.release = ?"]
        params: list = [match, release]
        if family:
            where.append("c.family = ?")
            params.append(family)
        if not include_withdrawn:
            where.append("c.withdrawn = 0")
        if baseline:
            where.append(
                "EXISTS (SELECT 1 FROM baseline_members m "
                "WHERE m.baseline = ? AND m.control_id = c.id)"
            )
            params.append(baseline)
        joined = (
            "FROM controls_fts JOIN controls c "
            "ON c.release = controls_fts.release AND c.id = controls_fts.id "
            "WHERE " + " AND ".join(where)
        )
        total = self.conn.execute(f"SELECT count(*) {joined}", params).fetchone()[0]
        rows = self.conn.execute(
            "SELECT c.id, c.title, c.family, c.parent_id, c.withdrawn, "
            "snippet(controls_fts, -1, '[', ']', ' ... ', 24) AS snippet, "
            "bm25(controls_fts, 0, 0, 10.0, 3.0, 1.0) AS score "
            f"{joined} ORDER BY score, c.sort_key LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["withdrawn"] = bool(item["withdrawn"])
            item["score"] = round(-item["score"], 3)
            results.append(item)
        return total, results


def fts_query(text: str, any_word: bool = False) -> str:
    """Turn free text into a safe FTS5 query.

    Every word becomes a quoted phrase so FTS5 operators and punctuation in
    the input cannot change the query's meaning. Words are ANDed unless
    any_word is set, which ORs them. A trailing asterisk keeps its prefix
    meaning, so "authent*" matches authenticate.
    https://www.sqlite.org/fts5.html#full_text_query_syntax
    """
    terms = []
    for word in text.split():
        prefix = word.endswith("*")
        word = word.strip('*"').replace('"', '""')
        if not word:
            continue
        terms.append(f'"{word}"*' if prefix else f'"{word}"')
    if not terms:
        raise ValueError("query has no searchable words")
    return " OR ".join(terms) if any_word else " ".join(terms)


def _statement_tree(rows: list[sqlite3.Row]) -> list[dict]:
    """Turn flat statement rows into a nested list, keeping file order."""
    nodes = {
        row["id"]: {
            "id": row["id"],
            "label": row["label"],
            "text": row["text"],
            "items": [],
        }
        for row in rows
    }
    roots: list[dict] = []
    for row in rows:
        node = nodes[row["id"]]
        parent = nodes.get(row["parent_id"]) if row["parent_id"] else None
        (parent["items"] if parent else roots).append(node)
    return roots


def open_store(path: Path | None = None) -> Store:
    """Open the store read only. Raises StoreError if it is missing or stale."""
    path = path or db_path()
    if not path.exists():
        raise StoreError(
            f"No store at {path}. Run: uv run python -m crosswalk_mcp.store build"
        )
    # mode=ro makes the connection refuse writes at the SQLite level.
    # https://www.sqlite.org/uri.html
    conn = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False
    )
    store = Store(conn)
    version = store.meta().get("schema_version")
    if version != str(SCHEMA_VERSION):
        store.close()
        raise StoreError(
            f"Store schema {version} does not match code schema {SCHEMA_VERSION}. "
            "Rebuild with: uv run python -m crosswalk_mcp.store build"
        )
    return store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m crosswalk_mcp.store",
        description="Build or inspect the SQLite store.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build_cmd = sub.add_parser("build", help="build the store from data/raw")
    build_cmd.add_argument("--raw", type=Path, default=None, help="raw source dir")
    build_cmd.add_argument("--out", type=Path, default=None, help="output file")
    sub.add_parser("status", help="show what the store was built from")
    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            report = build(args.raw, args.out)
            print(f"built {report.path}")
            print(f"manifest_hash {report.manifest_hash}")
            for table, count in report.counts.items():
                print(f"  {table:20} {count:>7}")
        elif args.command == "status":
            store = open_store()
            meta = store.meta()
            print(f"store {db_path()}")
            print(f"schema_version {meta['schema_version']}")
            print(f"manifest_hash {meta['manifest_hash']}")
            print(f"built_at {meta['built_at']}")
            for release in store.releases():
                count = store.conn.execute(
                    "SELECT count(*) FROM controls WHERE release = ?",
                    (release["release"],),
                ).fetchone()[0]
                print(f"  800-53 {release['release']}: {count} controls")
            for baseline in store.baselines():
                print(
                    f"  800-53B {baseline['baseline']}: "
                    f"{baseline['member_count']} controls"
                )
            csf_counts = store.csf_counts()
            print(
                f"  CSF 2.0: {csf_counts['active'].get('subcategory', 0)} active "
                f"subcategories, {sum(csf_counts['legacy'].values())} legacy ids"
            )
            store.close()
    except (StoreError, SnapshotError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
