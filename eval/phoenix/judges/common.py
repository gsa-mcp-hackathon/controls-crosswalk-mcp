"""The judge model, shared by both judges.

Judges use JUDGE_MODEL, which should differ from AGENT_MODEL so the agent
is not grading itself.
"""

from __future__ import annotations

from model_env import judge_temperature, load_model_env, model_name, provider
from phoenix.evals import LLM


def judge_llm() -> LLM:
    """Phoenix's LLM wrapper for the chosen provider. Keys and endpoints
    are read from the environment by the SDK underneath.

    OpenAI goes through the OpenAI SDK. watsonx.ai goes through LiteLLM,
    which expects the model id with a "watsonx/" prefix:
    https://docs.litellm.ai/docs/providers/watsonx
    """
    load_model_env()
    model = model_name("JUDGE_MODEL")
    if provider() == "watsonx":
        return LLM(provider="litellm", model=f"watsonx/{model}")
    return LLM(provider="openai", model=model, client="openai")


def judge_settings() -> dict[str, float]:
    """Per-request settings for a judge call. Passed to the evaluator, which
    forwards them with every request."""
    load_model_env()
    return judge_temperature(model_name("JUDGE_MODEL"))


def text_of(value) -> str:
    """Phoenix hands judges dicts or strings depending on the column."""
    if isinstance(value, dict):
        return str(value.get("query") or value.get("responses") or value)
    return "" if value is None else str(value)
