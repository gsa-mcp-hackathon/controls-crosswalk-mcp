"""Snapshot fetch and manifest behavior, tested offline with a mock transport."""

from __future__ import annotations

import json

import httpx
import pytest

from crosswalk_mcp import snapshot
from crosswalk_mcp.sources import SOURCES, Source


def _source(key: str = "demo", filename: str = "demo.json") -> Source:
    return Source(
        key=key,
        url=f"https://example.gov/{filename}",
        filename=filename,
        publisher="test",
        description="test source",
        pin="abc123",
    )


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_writes_file_and_entry(tmp_path):
    body = json.dumps({"hello": "world"}).encode()
    client = _client(lambda request: httpx.Response(200, content=body))
    entry = snapshot.fetch_source(_source(), tmp_path, client)
    assert (tmp_path / "demo.json").read_bytes() == body
    assert entry.bytes == len(body)
    assert entry.sha256 == snapshot.sha256_file(tmp_path / "demo.json")
    assert entry.pin == "abc123"
    assert entry.fetched_at != "existing"


def test_existing_file_is_not_refetched_unless_forced(tmp_path):
    (tmp_path / "demo.json").write_text("{}")
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, content=b'{"new": true}')

    entry = snapshot.fetch_source(_source(), tmp_path, _client(handler))
    assert entry.fetched_at == "existing"
    assert calls == []

    entry = snapshot.fetch_source(_source(), tmp_path, _client(handler), force=True)
    assert len(calls) == 1
    assert (tmp_path / "demo.json").read_text() == '{"new": true}'


def test_http_error_leaves_no_file(tmp_path):
    client = _client(lambda request: httpx.Response(404))
    with pytest.raises(snapshot.SnapshotError, match="HTTP 404"):
        snapshot.fetch_source(_source(), tmp_path, client)
    assert list(tmp_path.iterdir()) == []


def test_invalid_json_is_rejected(tmp_path):
    client = _client(lambda request: httpx.Response(200, content=b"<html>"))
    with pytest.raises(snapshot.SnapshotError, match="not valid JSON"):
        snapshot.fetch_source(_source(), tmp_path, client)
    assert list(tmp_path.iterdir()) == []


def test_oversized_response_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "MAX_SOURCE_BYTES", 10)
    client = _client(lambda request: httpx.Response(200, content=b"x" * 11))
    with pytest.raises(snapshot.SnapshotError, match="exceeded"):
        snapshot.fetch_source(_source(), tmp_path, client)
    assert list(tmp_path.iterdir()) == []


def test_manifest_hash_is_order_independent(tmp_path):
    a = snapshot.ManifestEntry("a", "u", "", "a.json", 1, "aa", "t")
    b = snapshot.ManifestEntry("b", "u", "", "b.json", 1, "bb", "t")
    assert snapshot.manifest_hash([a, b]) == snapshot.manifest_hash([b, a])
    assert snapshot.manifest_hash([a]) != snapshot.manifest_hash([a, b])


def test_verify_detects_tampering(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "SOURCES", (_source(),))
    body = b'{"v": 1}'
    client = _client(lambda request: httpx.Response(200, content=body))
    entry = snapshot.fetch_source(_source(), tmp_path, client)
    snapshot.write_manifest([entry], tmp_path)
    assert snapshot.verify(tmp_path) == []

    (tmp_path / "demo.json").write_bytes(b'{"v": 2}')
    assert snapshot.verify(tmp_path) == ["demo: sha256 mismatch"]

    (tmp_path / "demo.json").unlink()
    assert snapshot.verify(tmp_path) == ["demo: file missing (demo.json)"]


def test_fetch_refuses_a_cached_file_that_changed(tmp_path, monkeypatch):
    """A plain fetch must not write a new manifest around a changed file."""
    monkeypatch.setattr(snapshot, "SOURCES", (_source(),))
    client = _client(lambda request: httpx.Response(200, content=b'{"v": 1}'))
    snapshot.fetch_all(tmp_path, client=client)
    recorded = snapshot.read_manifest(tmp_path)

    (tmp_path / "demo.json").write_bytes(b'{"v": 2}')
    with pytest.raises(snapshot.SnapshotError, match="does not match the manifest"):
        snapshot.fetch_all(tmp_path, client=client)
    assert snapshot.read_manifest(tmp_path) == recorded
    assert snapshot.verify(tmp_path) == ["demo: sha256 mismatch"]

    # Downloading the file again is the way out.
    snapshot.fetch_all(tmp_path, client=client, force=True)
    assert snapshot.verify(tmp_path) == []


def test_fetch_reports_when_the_publisher_changed_a_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(snapshot, "SOURCES", (_source(),))
    old = _client(lambda request: httpx.Response(200, content=b'{"v": 1}'))
    snapshot.fetch_all(tmp_path, client=old)
    assert "snapshot changed" not in capsys.readouterr().err

    new = _client(lambda request: httpx.Response(200, content=b'{"v": 2}'))
    snapshot.fetch_all(tmp_path, client=new, force=True)
    assert "snapshot changed" in capsys.readouterr().err
    assert snapshot.verify(tmp_path) == []


def test_verify_reports_sources_missing_from_manifest(tmp_path):
    snapshot.write_manifest([], tmp_path)
    problems = snapshot.verify(tmp_path)
    assert len(problems) == len(SOURCES)
    assert all(problem.endswith("not in manifest") for problem in problems)


def test_every_github_source_is_pinned_to_a_commit():
    for source in SOURCES:
        if "raw.githubusercontent.com" in source.url:
            assert len(source.pin) == 40, source.key
            assert source.pin in source.url, source.key
