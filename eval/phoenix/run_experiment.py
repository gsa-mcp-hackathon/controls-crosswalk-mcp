#!/usr/bin/env python
"""Run the agent over a Phoenix dataset and score it with the judges.

    uv run eval/phoenix/run_experiment.py --dataset-name crosswalk-eval-0
    uv run eval/phoenix/run_experiment.py --dataset-name crosswalk-eval-0 \
        --system-prompt-version v1 --experiment-description "no scope rules"
    uv run eval/phoenix/run_experiment.py --dataset-name crosswalk-eval-0 \
        --no-tools --repetitions 5

--no-tools runs the baseline: the same model with no server, so the two
experiments show what the tools add. --repetitions asks every question
several times, which shows how consistent the answers are.

Phoenix must be running (`uv run arize-phoenix serve`) and the dataset must
have been uploaded with create_dataset.py. Results and per-question traces
appear in the Phoenix UI.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agent import DEFAULT_PROJECT, CrosswalkAgent
from create_dataset import load_frame, registry
from dotenv import load_dotenv
from judges import check_answer_scope, match_expected_response

HERE = Path(__file__).resolve().parent
PROMPT_VERSIONS = sorted(
    p.stem.removeprefix("system_prompt_")
    for p in (HERE / "prompts").glob("system_prompt_*.txt")
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dataset-name", required=True, help="name in datasets.yaml")
    parser.add_argument(
        "--system-prompt-version", choices=PROMPT_VERSIONS, default="v2"
    )
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="baseline: the model answers from memory, without the server",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="times to ask each question (default 1)",
    )
    parser.add_argument(
        "--task-timeout",
        type=int,
        default=600,
        help="seconds allowed per question; Phoenix's own default is 60",
    )
    parser.add_argument("--project-name", default=DEFAULT_PROJECT)
    parser.add_argument("--phoenix-endpoint", default=None)
    parser.add_argument("--experiment-name", default=None)
    parser.add_argument("--experiment-description", default=None)
    parser.add_argument("--dataset-version-id", default=None)
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="skip checking the local CSV before using the Phoenix dataset",
    )
    args = parser.parse_args(argv)
    if args.repetitions < 1:
        parser.error("--repetitions must be 1 or more")
    load_dotenv()

    datasets = registry()
    if args.dataset_name not in datasets:
        print(f"unknown dataset {args.dataset_name!r}", file=sys.stderr)
        return 1
    if not args.no_validate:
        frame = load_frame(datasets[args.dataset_name])
        print(f"local CSV ok: {len(frame)} rows")

    from phoenix.client import Client

    endpoint = (
        args.phoenix_endpoint
        or os.environ.get("PHOENIX_COLLECTOR_ENDPOINT")
        or "http://localhost:6006"
    )
    client = Client(base_url=endpoint)
    dataset = client.datasets.get_dataset(
        dataset=args.dataset_name, version_id=args.dataset_version_id
    )
    agent = CrosswalkAgent(
        system_prompt_version=args.system_prompt_version,
        project_name=args.project_name,
        phoenix_endpoint=endpoint,
        use_tools=not args.no_tools,
    )
    # The baseline has its own prompt, so the prompt version does not apply.
    variant = "baseline" if args.no_tools else args.system_prompt_version
    name = args.experiment_name or f"{args.dataset_name}-{variant}"
    description = args.experiment_description or (
        f"agent {os.environ.get('AGENT_MODEL')}, "
        f"judge {os.environ.get('JUDGE_MODEL')}, "
        f"{'no tools' if args.no_tools else 'prompt ' + variant}, "
        f"{args.repetitions} run(s) per question"
    )
    client.experiments.run_experiment(
        dataset=dataset,
        task=agent.create_experiment_task(),
        evaluators=[check_answer_scope, match_expected_response],
        experiment_name=name,
        experiment_description=description,
        experiment_metadata={
            "system_prompt_version": variant,
            "tools": not args.no_tools,
            "repetitions": args.repetitions,
            "agent_model": os.environ.get("AGENT_MODEL"),
            "judge_model": os.environ.get("JUDGE_MODEL"),
        },
        # One question can take many tool calls. Phoenix stops a task after
        # 60 seconds unless told otherwise.
        # https://docs.arize.com/phoenix
        timeout=args.task_timeout,
        repetitions=args.repetitions,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
