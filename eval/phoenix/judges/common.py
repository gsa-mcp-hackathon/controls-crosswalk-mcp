"""The judge model, shared by both judges.

Judges use JUDGE_MODEL, which should differ from AGENT_MODEL so the agent
is not grading itself. Both go through the same gateway as the agent.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from phoenix.evals import LLM


def judge_llm() -> LLM:
    load_dotenv()
    base_url = os.environ.get("USAI_BASE_URL")
    api_key = os.environ.get("USAI_API_KEY")
    if not base_url or not api_key:
        raise RuntimeError("Set USAI_BASE_URL and USAI_API_KEY in the root .env file.")
    model = os.environ.get("JUDGE_MODEL", "USAI_claude_4_5_opus")
    # Phoenix's LLM wrapper drives the OpenAI SDK; base_url and api_key are
    # passed through to it so the gateway is used instead of api.openai.com.
    # Extra keyword arguments go to the SDK client, not to each request, so
    # temperature is left at the model default; the classification prompt
    # asks for a single word, which keeps judgments stable.
    return LLM(
        provider="openai",
        model=model,
        client="openai",
        sync_client_kwargs={"base_url": base_url, "api_key": api_key},
        async_client_kwargs={"base_url": base_url, "api_key": api_key},
    )


def text_of(value) -> str:
    """Phoenix hands judges dicts or strings depending on the column."""
    if isinstance(value, dict):
        return str(value.get("query") or value.get("responses") or value)
    return "" if value is None else str(value)
