#!/usr/bin/env python
"""Run the agent over a Phoenix dataset and score it with the judges.

    uv run eval/phoenix/run_experiment.py --dataset-name crosswalk-eval-0
    uv run eval/phoenix/run_experiment.py --dataset-name crosswalk-eval-0 \
        --system-prompt-version v1 --experiment-description "no scope rules"

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
    p.stem.removeprefix("system_prompt_") for p in (HERE / "prompts").glob("*.txt")
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dataset-name", required=True, help="name in datasets.yaml")
    parser.add_argument(
        "--system-prompt-version", choices=PROMPT_VERSIONS, default="v2"
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
    )
    name = args.experiment_name or f"{args.dataset_name}-{args.system_prompt_version}"
    description = args.experiment_description or (
        f"agent {os.environ.get('AGENT_MODEL', 'default')}, "
        f"judge {os.environ.get('JUDGE_MODEL', 'default')}, "
        f"prompt {args.system_prompt_version}"
    )
    client.experiments.run_experiment(
        dataset=dataset,
        task=agent.create_experiment_task(),
        evaluators=[check_answer_scope, match_expected_response],
        experiment_name=name,
        experiment_description=description,
        experiment_metadata={
            "system_prompt_version": args.system_prompt_version,
            "agent_model": os.environ.get("AGENT_MODEL"),
            "judge_model": os.environ.get("JUDGE_MODEL"),
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
