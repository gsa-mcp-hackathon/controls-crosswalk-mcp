"""Model settings shared by the agent and the judges.

Both talk to a chat model through one provider, chosen by MODEL_PROVIDER
in the root .env file. Each provider uses the setting names its own SDK
already reads, so no key is ever passed in code.

    MODEL_PROVIDER    optional, "openai" (default) or "watsonx"
    AGENT_MODEL       required, the model that answers the questions
    JUDGE_MODEL       required, the model that grades the answers
    JUDGE_TEMPERATURE optional, defaults to 0

OpenAI: https://platform.openai.com/docs/api-reference/authentication

    OPENAI_API_KEY    required
    OPENAI_BASE_URL   optional, only for an OpenAI-compatible endpoint

IBM watsonx.ai:
https://dataplatform.cloud.ibm.com/docs/content/wsj/analyze-data/fm-credentials.html

    WATSONX_URL         required, the regional endpoint
    WATSONX_API_KEY     required, an IBM Cloud API key
    WATSONX_PROJECT_ID  required, or WATSONX_SPACE_ID for a deployment space
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

PROVIDERS = ("openai", "watsonx")


def provider() -> str:
    """The provider named by MODEL_PROVIDER. OpenAI when it is not set."""
    load_dotenv()
    name = os.environ.get("MODEL_PROVIDER", "").strip().lower() or "openai"
    if name not in PROVIDERS:
        raise RuntimeError(
            f"MODEL_PROVIDER is {name!r}. Use one of: {', '.join(PROVIDERS)}."
        )
    return name


def _is_set(variable: str) -> bool:
    return bool(os.environ.get(variable, "").strip())


def load_model_env() -> None:
    """Load .env and check that the chosen provider's settings are present.

    Only the names of missing settings are reported, never their values.
    """
    if provider() == "watsonx":
        missing = [v for v in ("WATSONX_URL", "WATSONX_API_KEY") if not _is_set(v)]
        if not (_is_set("WATSONX_PROJECT_ID") or _is_set("WATSONX_SPACE_ID")):
            missing.append("WATSONX_PROJECT_ID")
        if missing:
            raise RuntimeError(f"Set {', '.join(missing)} in the root .env file.")
        return
    # The OpenAI SDK treats an empty OPENAI_BASE_URL as a real address and
    # then fails to connect, so a blank value is removed here and the SDK
    # falls back to api.openai.com.
    if not _is_set("OPENAI_BASE_URL"):
        os.environ.pop("OPENAI_BASE_URL", None)
    if not _is_set("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY in the root .env file.")


def model_name(variable: str) -> str:
    """The model id from AGENT_MODEL or JUDGE_MODEL. There is no default,
    so a run always records the model that was chosen on purpose."""
    name = os.environ.get(variable, "").strip()
    if not name:
        raise RuntimeError(f"Set {variable} in the root .env file.")
    return name


def fixed_temperature(model: str) -> bool:
    """True for models that only accept their default temperature.

    OpenAI's reasoning models (the o series and gpt-5, but not gpt-5-chat)
    reject any other value. This is the same rule langchain-openai applies
    to the agent model.
    https://platform.openai.com/docs/guides/reasoning
    """
    name = model.lower()
    if name.startswith(("o1", "o3", "o4")):
        return True
    return name.startswith("gpt-5") and "chat" not in name


def judge_temperature(model: str) -> dict[str, float]:
    """Request settings that pin the judge to temperature 0 where the
    model allows it. Set JUDGE_TEMPERATURE to another number to change it,
    or to an empty value to send no temperature at all."""
    raw = os.environ.get("JUDGE_TEMPERATURE", "0").strip()
    if not raw or fixed_temperature(model):
        return {}
    return {"temperature": float(raw)}
