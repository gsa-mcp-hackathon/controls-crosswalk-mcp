#!/usr/bin/env python
"""Upload a registered dataset to Phoenix.

    uv run eval/phoenix/create_dataset.py --list
    uv run eval/phoenix/create_dataset.py --dataset-name crosswalk-eval-0 --dry-run
    uv run eval/phoenix/create_dataset.py --dataset-name crosswalk-eval-0

Datasets are registered in datasets.yaml. --dry-run validates the CSV and
prints its shape without talking to Phoenix.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent


def registry() -> dict:
    with (HERE / "datasets.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)["datasets"]


def load_frame(entry: dict, csv_path: str | None = None) -> pd.DataFrame:
    path = Path(csv_path) if csv_path else HERE / entry["csv_path"]
    frame = pd.read_csv(path)
    missing = [
        c for c in [*entry["input_keys"], *entry["output_keys"]] if c not in frame
    ]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    if frame.empty:
        raise ValueError(f"{path}: no rows")
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--list", action="store_true", help="list registered datasets")
    parser.add_argument("--dataset-name", help="name in datasets.yaml")
    parser.add_argument("--phoenix-name", help="name to use in Phoenix (default: same)")
    parser.add_argument("--csv-path", help="override the registered CSV path")
    parser.add_argument("--dry-run", action="store_true", help="validate only")
    parser.add_argument(
        "--phoenix-endpoint",
        default=None,
        help="Phoenix base URL (default: PHOENIX_COLLECTOR_ENDPOINT or localhost:6006)",
    )
    args = parser.parse_args(argv)
    load_dotenv()
    datasets = registry()

    if args.list or not args.dataset_name:
        for name, entry in datasets.items():
            print(f"{name:20} {entry['csv_path']}  {entry['description']}")
        return 0
    if args.dataset_name not in datasets:
        print(f"unknown dataset {args.dataset_name!r}; use --list", file=sys.stderr)
        return 1
    entry = datasets[args.dataset_name]
    frame = load_frame(entry, args.csv_path)
    print(f"{args.dataset_name}: {len(frame)} rows, columns {list(frame.columns)}")
    if args.dry_run:
        return 0

    from phoenix.client import Client

    endpoint = (
        args.phoenix_endpoint
        or os.environ.get("PHOENIX_COLLECTOR_ENDPOINT")
        or "http://localhost:6006"
    )
    client = Client(base_url=endpoint)
    dataset = client.datasets.create_dataset(
        name=args.phoenix_name or args.dataset_name,
        dataframe=frame,
        input_keys=entry["input_keys"],
        output_keys=entry["output_keys"],
        dataset_description=entry["description"],
    )
    print(f"created Phoenix dataset {dataset.name} ({dataset.id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
