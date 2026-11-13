"""The gold question set stays consistent with the store and the CSV."""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

import pytest

from crosswalk_mcp import store
from crosswalk_mcp.tools import common

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "eval"))
sys.path.insert(0, str(REPO_ROOT / "eval" / "phoenix"))

import gold_check  # noqa: E402
from build_dataset import read_pairs  # noqa: E402

DATASET = REPO_ROOT / "eval" / "phoenix" / "datasets" / "crosswalk-eval-0"
REAL_STORE = Path("data") / store.DB_NAME


def test_csv_matches_evaluation_xml():
    pairs = read_pairs(DATASET / "evaluation.xml")
    with (DATASET / "examples" / "crosswalk-eval-0.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [(r["query"], r["responses"]) for r in rows] == pairs
    assert len(pairs) == len(gold_check.RESOLVERS) == 12


@pytest.mark.skipif(not REAL_STORE.exists(), reason="real store not built")
def test_gold_answers_hold_against_real_store():
    common.configure_store(REAL_STORE)
    try:
        assert asyncio.run(gold_check.check()) == []
    finally:
        common.configure_store(None)


@pytest.mark.skipif(not REAL_STORE.exists(), reason="real store not built")
def test_stdio_toolbox_launches_the_server():
    """The harness launches the server the way a client would. Needs the
    eval dependency group; skipped when it is not installed."""
    pytest.importorskip("langchain_core")
    import json

    from mcp_tools import McpToolbox

    async def probe():
        async with McpToolbox() as toolbox:
            names = {t.name for t in toolbox.tools}
            tool = next(t for t in toolbox.tools if t.name == "controls_get_ksi")
            ok = json.loads(await tool.ainvoke({"ksi_id": "KSI-CED"}))
            bad = json.loads(await tool.ainvoke({"ksi_id": "AC-2"}))
        return names, ok, bad

    names, ok, bad = asyncio.run(probe())
    assert "controls_crosswalk" in names and len(names) == 9
    assert ok["theme"]["id"] == "KSI-CED"
    assert "not a FedRAMP KSI identifier" in bad["error"]
