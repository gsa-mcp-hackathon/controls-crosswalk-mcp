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
    assert len(pairs) == len(gold_check.RESOLVERS) == 15


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


class _StandInModel:
    """Builds a scripted chat model so the agent loop runs without a key."""

    @staticmethod
    def scripted(*messages):
        from langchain_core.language_models.fake_chat_models import (
            GenericFakeChatModel,
        )

        class Scripted(GenericFakeChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        return Scripted(messages=iter(messages))


def test_baseline_agent_runs_without_the_server():
    """The no-tool baseline answers from the model alone and uses its own
    prompt, which says there are no tools."""
    pytest.importorskip("langchain")
    from agent import CrosswalkAgent
    from langchain_core.messages import AIMessage

    model = _StandInModel.scripted(AIMessage(content="I do not know."))
    agent = CrosswalkAgent(trace=False, use_tools=False, model=model)
    assert "no tools" in agent.system_prompt
    assert asyncio.run(agent.run("How many controls were added?")) == "I do not know."


@pytest.mark.skipif(not REAL_STORE.exists(), reason="real store not built")
def test_agent_loop_calls_tools_over_stdio():
    """A scripted model asks for one tool, reads the result, and answers.
    This covers the whole path a real model run takes, minus the model."""
    pytest.importorskip("langchain")
    from agent import CrosswalkAgent
    from langchain_core.messages import AIMessage

    call = {"name": "controls_diff_releases", "args": {}, "id": "call-1"}
    model = _StandInModel.scripted(
        AIMessage(content="", tool_calls=[call]), AIMessage(content="3")
    )
    agent = CrosswalkAgent(trace=False, model=model)
    assert asyncio.run(agent.run("How many controls were added in 5.2.0?")) == "3"


def test_model_provider_setting(monkeypatch):
    """MODEL_PROVIDER picks OpenAI or watsonx.ai, and a missing watsonx
    setting is reported by name. Empty values are set here, not removed,
    so a developer's own .env cannot fill them back in."""
    pytest.importorskip("dotenv")
    import model_env

    monkeypatch.setenv("MODEL_PROVIDER", "")
    assert model_env.provider() == "openai"

    monkeypatch.setenv("MODEL_PROVIDER", "bedrock")
    with pytest.raises(RuntimeError, match="Use one of"):
        model_env.provider()

    monkeypatch.setenv("MODEL_PROVIDER", "WatsonX")
    assert model_env.provider() == "watsonx"
    monkeypatch.setenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
    monkeypatch.setenv("WATSONX_API_KEY", "")
    monkeypatch.setenv("WATSONX_PROJECT_ID", "")
    monkeypatch.setenv("WATSONX_SPACE_ID", "")
    with pytest.raises(RuntimeError) as error:
        model_env.load_model_env()
    assert "WATSONX_API_KEY, WATSONX_PROJECT_ID" in str(error.value)
    assert "WATSONX_URL" not in str(error.value)


def test_watsonx_judge_goes_through_litellm(monkeypatch):
    """The watsonx.ai judge is built with LiteLLM's "watsonx/" model
    prefix. Building it makes no network call, so placeholders are enough."""
    pytest.importorskip("phoenix.evals")
    pytest.importorskip("litellm")
    from judges.common import judge_llm, judge_settings

    monkeypatch.setenv("MODEL_PROVIDER", "watsonx")
    monkeypatch.setenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
    monkeypatch.setenv("WATSONX_API_KEY", "placeholder")
    monkeypatch.setenv("WATSONX_PROJECT_ID", "placeholder")
    monkeypatch.setenv("JUDGE_MODEL", "mistral-large-2512")
    monkeypatch.setenv("JUDGE_TEMPERATURE", "0")
    assert judge_llm().model == "watsonx/mistral-large-2512"
    assert judge_settings() == {"temperature": 0.0}
