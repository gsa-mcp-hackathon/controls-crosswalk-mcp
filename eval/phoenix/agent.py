#!/usr/bin/env python
"""CrosswalkAgent: a LangChain agent that answers with the server's tools.

    uv run eval/phoenix/agent.py "How many controls were added in 5.2.0?"

The agent drives an OpenAI-compatible chat model through the gateway named
by USAI_BASE_URL and USAI_API_KEY, launches the MCP server over stdio, and
is traced into Phoenix. run_experiment.py uses it as the experiment task.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from mcp_tools import McpToolbox

HERE = Path(__file__).resolve().parent
DEFAULT_PROJECT = "controls-crosswalk-eval"


def load_system_prompt(version: str) -> str:
    path = HERE / "prompts" / f"system_prompt_{version}.txt"
    if not path.exists():
        known = sorted(
            p.stem.removeprefix("system_prompt_") for p in path.parent.glob("*.txt")
        )
        raise FileNotFoundError(f"No prompt version {version!r}. Known: {known}")
    return path.read_text(encoding="utf-8")


def gateway_model(model_env: str, default: str) -> ChatOpenAI:
    """A chat model on the gateway. temperature 0 keeps runs comparable."""
    load_dotenv()
    base_url = os.environ.get("USAI_BASE_URL")
    api_key = os.environ.get("USAI_API_KEY")
    if not base_url or not api_key:
        raise RuntimeError("Set USAI_BASE_URL and USAI_API_KEY in the root .env file.")
    return ChatOpenAI(
        model=os.environ.get(model_env, default),
        base_url=base_url,
        api_key=api_key,
        temperature=0,
        timeout=120,
        max_retries=2,
    )


def instrument(project_name: str, endpoint: str | None) -> None:
    """Send LangChain traces to Phoenix. Safe to call more than once."""
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from phoenix.otel import register

    if LangChainInstrumentor().is_instrumented_by_opentelemetry:
        return
    provider = register(
        project_name=project_name,
        endpoint=endpoint,
        batch=True,
        set_global_tracer_provider=False,
        verbose=False,
    )
    LangChainInstrumentor().instrument(tracer_provider=provider)


class CrosswalkAgent:
    """One configured agent. Call `run(question)` for an answer string."""

    def __init__(
        self,
        system_prompt_version: str = "v2",
        project_name: str = DEFAULT_PROJECT,
        phoenix_endpoint: str | None = None,
        trace: bool = True,
        max_steps: int = 60,
    ):
        self.system_prompt = load_system_prompt(system_prompt_version)
        self.model = gateway_model("AGENT_MODEL", "USAI_claude_4_5_sonnet")
        self.max_steps = max_steps
        if trace:
            instrument(
                project_name,
                phoenix_endpoint or os.environ.get("PHOENIX_COLLECTOR_ENDPOINT"),
            )

    async def run(self, question: str) -> str:
        async with McpToolbox() as toolbox:
            agent = create_agent(
                model=self.model,
                tools=toolbox.tools,
                system_prompt=self.system_prompt,
            )
            state = await agent.ainvoke(
                {"messages": [("user", question)]},
                config={"recursion_limit": self.max_steps},
            )
        for message in reversed(state["messages"]):
            if isinstance(message, AIMessage) and message.content:
                return _text(message.content)
        return ""

    def create_experiment_task(self):
        """A synchronous task for Phoenix experiments. Phoenix passes one
        dataset example; its input has the `query` column."""

        def task(example) -> str:
            return asyncio.run(self.run(example.input["query"]))

        return task


def _text(content) -> str:
    """Chat models may return a string or a list of content blocks."""
    if isinstance(content, str):
        return content.strip()
    parts = [b.get("text", "") for b in content if isinstance(b, dict)]
    return "\n".join(p for p in parts if p).strip()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    question = (
        " ".join(argv) or "How many SP 800-53 controls were added in release 5.2.0?"
    )
    agent = CrosswalkAgent(trace=False)
    print(asyncio.run(agent.run(question)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
