#!/usr/bin/env python
"""CrosswalkAgent: a LangChain agent that answers with the server's tools.

    uv run eval/phoenix/agent.py "How many controls were added in 5.2.0?"

    uv run eval/phoenix/agent.py --no-tools "How many controls were added?"

The agent drives a chat model through OpenAI or IBM watsonx.ai (settings
in model_env.py), launches the MCP server over stdio, and is traced into
Phoenix. run_experiment.py uses it as the experiment task.

With --no-tools the same model answers from memory, with no server. That
is the baseline: the gap between the two runs is what the server adds.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from mcp_tools import McpToolbox
from model_env import load_model_env, model_name, provider

HERE = Path(__file__).resolve().parent
DEFAULT_PROJECT = "controls-crosswalk-eval"


def load_system_prompt(version: str) -> str:
    path = HERE / "prompts" / f"system_prompt_{version}.txt"
    if not path.exists():
        known = sorted(
            p.stem.removeprefix("system_prompt_")
            for p in path.parent.glob("system_prompt_*.txt")
        )
        raise FileNotFoundError(f"No prompt version {version!r}. Known: {known}")
    return path.read_text(encoding="utf-8")


def load_baseline_prompt() -> str:
    """The prompt for the no-tool baseline. It keeps the same scope rules
    as v2 but tells the model it has no tools, so the comparison measures
    the tools and not a difference in instructions."""
    return (HERE / "prompts" / "baseline_prompt.txt").read_text(encoding="utf-8")


def agent_model() -> BaseChatModel:
    """The chat model named by AGENT_MODEL, on the chosen provider. Keys
    and endpoints are read from the environment by each SDK. temperature 0
    keeps runs comparable.
    """
    load_model_env()
    model = model_name("AGENT_MODEL")
    if provider() == "watsonx":
        # Imported here so an OpenAI run does not load the IBM SDK.
        # https://python.langchain.com/docs/integrations/chat/ibm_watsonx/
        from langchain_ibm import ChatWatsonx

        return ChatWatsonx(model_id=model, temperature=0)
    # langchain-openai leaves temperature out for reasoning models that
    # only accept their default.
    # https://python.langchain.com/docs/integrations/chat/openai/
    #
    # OpenAI's newer reasoning models refuse tool calls on the older Chat
    # Completions API, so calls to OpenAI itself use the Responses API.
    # An OpenAI-compatible endpoint set in OPENAI_BASE_URL may only offer
    # Chat Completions, so there the choice is left to langchain-openai.
    # https://platform.openai.com/docs/guides/migrate-to-responses
    own_endpoint = bool(os.environ.get("OPENAI_BASE_URL", "").strip())
    return ChatOpenAI(
        model=model,
        temperature=0,
        timeout=120,
        max_retries=2,
        use_responses_api=None if own_endpoint else True,
    )


def trace_endpoint(base: str | None) -> str:
    """The address Phoenix receives traces on, built from its base address.

    Phoenix sends an address passed in code exactly as given, so the base
    address alone gets a "405 Method Not Allowed" reply. The traces path
    has to be added here.
    https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing
    """
    base = (base or "http://localhost:6006").rstrip("/")
    return base if base.endswith("/v1/traces") else f"{base}/v1/traces"


def instrument(project_name: str, endpoint: str | None) -> None:
    """Send LangChain traces to Phoenix. Safe to call more than once.
    `endpoint` is the Phoenix base address, such as http://localhost:6006."""
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from phoenix.otel import register

    if LangChainInstrumentor().is_instrumented_by_opentelemetry:
        return
    provider = register(
        project_name=project_name,
        endpoint=trace_endpoint(endpoint),
        batch=True,
        set_global_tracer_provider=False,
        verbose=False,
    )
    LangChainInstrumentor().instrument(tracer_provider=provider)


_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def run_on_shared_loop(coroutine):
    """Run a coroutine on one event loop that lasts as long as the process.

    The OpenAI client keeps its network connections open between
    questions, and a connection only works on the event loop that opened
    it. asyncio.run starts and closes a new loop on every call, so the
    second question failed with "Event loop is closed". One loop on a
    background thread avoids that.
    https://docs.python.org/3/library/asyncio-task.html#asyncio.run_coroutine_threadsafe
    """
    global _loop
    with _loop_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(
                target=_loop.run_forever, daemon=True, name="eval-agent-loop"
            ).start()
    return asyncio.run_coroutine_threadsafe(coroutine, _loop).result()


class CrosswalkAgent:
    """One configured agent. Call `run(question)` for an answer string."""

    def __init__(
        self,
        system_prompt_version: str = "v2",
        project_name: str = DEFAULT_PROJECT,
        phoenix_endpoint: str | None = None,
        trace: bool = True,
        max_steps: int = 60,
        use_tools: bool = True,
        model: BaseChatModel | None = None,
    ):
        self.use_tools = use_tools
        self.system_prompt = (
            load_system_prompt(system_prompt_version)
            if use_tools
            else load_baseline_prompt()
        )
        # `model` lets a test pass a stand-in so no key is needed.
        self.model = model or agent_model()
        self.max_steps = max_steps
        if trace:
            instrument(
                project_name,
                phoenix_endpoint or os.environ.get("PHOENIX_COLLECTOR_ENDPOINT"),
            )

    async def run(self, question: str) -> str:
        if self.use_tools:
            async with McpToolbox() as toolbox:
                state = await self._ask(question, toolbox.tools)
        else:
            state = await self._ask(question, [])
        for message in reversed(state["messages"]):
            if isinstance(message, AIMessage) and message.content:
                return _text(message.content)
        return ""

    async def _ask(self, question: str, tools: list) -> dict:
        agent = create_agent(
            model=self.model, tools=tools, system_prompt=self.system_prompt
        )
        return await agent.ainvoke(
            {"messages": [("user", question)]},
            config={"recursion_limit": self.max_steps},
        )

    def create_experiment_task(self):
        """A synchronous task for Phoenix experiments. Phoenix passes one
        dataset example; its input has the `query` column."""

        def task(example) -> str:
            return run_on_shared_loop(self.run(example.input["query"]))

        return task


def _text(content) -> str:
    """Chat models may return a string or a list of content blocks."""
    if isinstance(content, str):
        return content.strip()
    parts = [b.get("text", "") for b in content if isinstance(b, dict)]
    return "\n".join(p for p in parts if p).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask the agent one question.")
    parser.add_argument("question", nargs="*")
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="baseline: answer from the model's memory, without the server",
    )
    args = parser.parse_args(argv)
    question = (
        " ".join(args.question)
        or "How many SP 800-53 controls were added in release 5.2.0?"
    )
    agent = CrosswalkAgent(trace=False, use_tools=not args.no_tools)
    print(asyncio.run(agent.run(question)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
