"""Fetch the pinned sources and record a manifest of exactly what was fetched.

The manifest is the server's notion of a data snapshot. Its hash is returned
with every tool result so an answer can always be traced to the bytes that
produced it. Run this as an operator, not from a tool:

    uv run python -m crosswalk_mcp.snapshot fetch
    uv run python -m crosswalk_mcp.snapshot fetch --force --only fedramp_rules
    uv run python -m crosswalk_mcp.snapshot verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from crosswalk_mcp.config import settings
from crosswalk_mcp.sources import SOURCES, SOURCES_BY_KEY, Source

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = 1

# The CPRT 800-53 exports are about 14 MB each. Leave headroom, but refuse
# anything that looks nothing like the files we expect.
MAX_SOURCE_BYTES = 64 * 1024 * 1024
FETCH_TIMEOUT = 120.0


class SnapshotError(RuntimeError):
    """A fetch or verification problem the operator needs to see."""


@dataclass(frozen=True)
class ManifestEntry:
    """What we know about one fetched file."""

    key: str
    url: str
    pin: str
    filename: str
    bytes: int
    sha256: str
    fetched_at: str


def raw_dir() -> Path:
    """Where fetched source files live. Not committed; see .gitignore."""
    return Path(settings.data_dir) / "raw"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_hash(entries: list[ManifestEntry]) -> str:
    """One hash over the set of file hashes, independent of fetch order."""
    joined = "\n".join(
        f"{entry.key}:{entry.sha256}" for entry in sorted(entries, key=lambda e: e.key)
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch_source(
    source: Source,
    dest_dir: Path,
    client: httpx.Client,
    force: bool = False,
) -> ManifestEntry:
    """Download one source to dest_dir unless it is already there.

    Writes to a temporary name and renames on success so a failed download
    never leaves a half written file behind.
    """
    dest = dest_dir / source.filename
    if dest.exists() and not force:
        return _entry_for(source, dest, fetched_at="existing")

    partial = dest.with_suffix(dest.suffix + ".part")
    received = 0
    try:
        with client.stream("GET", source.url) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes():
                    received += len(chunk)
                    if received > MAX_SOURCE_BYTES:
                        raise SnapshotError(
                            f"{source.key}: exceeded {MAX_SOURCE_BYTES} bytes"
                        )
                    handle.write(chunk)
    except httpx.HTTPStatusError as exc:
        partial.unlink(missing_ok=True)
        raise SnapshotError(
            f"{source.key}: HTTP {exc.response.status_code} from {source.url}"
        ) from None
    except httpx.RequestError as exc:
        partial.unlink(missing_ok=True)
        raise SnapshotError(f"{source.key}: request failed ({exc})") from None
    except SnapshotError:
        partial.unlink(missing_ok=True)
        raise

    # Every source is JSON. Refuse to keep a file that does not parse.
    try:
        with partial.open("rb") as handle:
            json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError):
        partial.unlink(missing_ok=True)
        raise SnapshotError(f"{source.key}: response was not valid JSON") from None

    partial.replace(dest)
    return _entry_for(source, dest, fetched_at=_utcnow())


def _entry_for(source: Source, path: Path, fetched_at: str) -> ManifestEntry:
    return ManifestEntry(
        key=source.key,
        url=source.url,
        pin=source.pin,
        filename=source.filename,
        bytes=path.stat().st_size,
        sha256=sha256_file(path),
        fetched_at=fetched_at,
    )


def write_manifest(entries: list[ManifestEntry], dest_dir: Path) -> Path:
    """Write manifest.json next to the fetched files and return its path."""
    ordered = sorted(entries, key=lambda e: e.key)
    payload = {
        "schema": MANIFEST_SCHEMA,
        "written_at": _utcnow(),
        "manifest_hash": manifest_hash(ordered),
        "sources": [asdict(entry) for entry in ordered],
    }
    path = dest_dir / MANIFEST_NAME
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def read_manifest(dest_dir: Path) -> dict:
    path = dest_dir / MANIFEST_NAME
    if not path.exists():
        raise SnapshotError(f"No manifest at {path}. Run the fetch command first.")
    return json.loads(path.read_text(encoding="utf-8"))


def verify(dest_dir: Path) -> list[str]:
    """Recompute every hash in the manifest. Returns a list of problems."""
    manifest = read_manifest(dest_dir)
    problems: list[str] = []
    for recorded in manifest["sources"]:
        path = dest_dir / recorded["filename"]
        if not path.exists():
            problems.append(f"{recorded['key']}: file missing ({path.name})")
            continue
        actual = sha256_file(path)
        if actual != recorded["sha256"]:
            problems.append(f"{recorded['key']}: sha256 mismatch")
    expected_keys = {source.key for source in SOURCES}
    recorded_keys = {recorded["key"] for recorded in manifest["sources"]}
    for key in sorted(expected_keys - recorded_keys):
        problems.append(f"{key}: not in manifest")
    return problems


def fetch_all(
    dest_dir: Path,
    only: list[str] | None = None,
    force: bool = False,
    client: httpx.Client | None = None,
) -> list[ManifestEntry]:
    """Fetch the selected sources, write the manifest, return the entries."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    selected = SOURCES if not only else tuple(SOURCES_BY_KEY[key] for key in only)

    # This is an operator run build step, so honor proxy and CA bundle
    # environment variables. Tools that serve requests must not do this.
    owned = client is None
    client = client or httpx.Client(
        timeout=FETCH_TIMEOUT, follow_redirects=False, trust_env=True
    )
    entries: list[ManifestEntry] = []
    try:
        for source in selected:
            entry = fetch_source(source, dest_dir, client, force=force)
            entries.append(entry)
            print(f"{entry.key:18} {entry.bytes:>10} bytes  {entry.sha256[:12]}")
    finally:
        if owned:
            client.close()

    # Keep entries for sources that were not part of this run.
    if only:
        try:
            previous = read_manifest(dest_dir)["sources"]
        except SnapshotError:
            previous = []
        kept = [
            ManifestEntry(**recorded)
            for recorded in previous
            if recorded["key"] not in only and recorded["key"] in SOURCES_BY_KEY
        ]
        entries = kept + entries

    path = write_manifest(entries, dest_dir)
    print(f"manifest written to {path} ({manifest_hash(entries)[:12]})")
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the raw data snapshot.")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="download sources and write manifest")
    fetch.add_argument("--force", action="store_true", help="refetch existing files")
    fetch.add_argument(
        "--only",
        action="append",
        choices=sorted(SOURCES_BY_KEY),
        help="fetch one source (repeatable)",
    )
    commands.add_parser("verify", help="recompute hashes against the manifest")

    args = parser.parse_args(argv)
    dest_dir = raw_dir()
    try:
        if args.command == "fetch":
            fetch_all(dest_dir, only=args.only, force=args.force)
            return 0
        problems = verify(dest_dir)
        for problem in problems:
            print(problem, file=sys.stderr)
        print("ok" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    except SnapshotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
