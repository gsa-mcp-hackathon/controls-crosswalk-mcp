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
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from crosswalk_mcp.config import settings
from crosswalk_mcp.loaders import sp800_53
from crosswalk_mcp.snapshot import SnapshotError, raw_dir, read_manifest, verify

DB_NAME = "crosswalk.sqlite"
SCHEMA_VERSION = 1

# Which raw source feeds which 800-53 release. The newest release is first,
# which makes it the default for lookups.
SP800_53_RELEASES: tuple[tuple[str, str], ...] = (
    ("5.2.0", "sp800_53_5_2_0"),
    ("5.1.1", "sp800_53_5_1_1"),
)

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
    ]
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


class Store:
    """Read side of the store. One instance can serve many lookups."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

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
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
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
            store.close()
    except (StoreError, SnapshotError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
