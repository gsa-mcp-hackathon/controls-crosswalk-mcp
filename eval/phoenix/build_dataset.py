#!/usr/bin/env python
"""Turn a dataset's evaluation.xml into the CSV the Phoenix harness uploads.

    uv run eval/phoenix/build_dataset.py --dataset-name crosswalk-eval-0

Reads datasets/<name>/evaluation.xml and writes
datasets/<name>/examples/<name>.csv with the columns query and responses.
The XML is the source of truth; the CSV is generated and committed so the
harness and the deterministic check always see the same questions.
"""

from __future__ import annotations

import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read_pairs(xml_path: Path) -> list[tuple[str, str]]:
    """The (question, answer) pairs in an evaluation.xml, in file order."""
    root = ET.parse(xml_path).getroot()
    pairs = []
    for pair in root.findall("qa_pair"):
        question = (pair.findtext("question") or "").strip()
        answer = (pair.findtext("answer") or "").strip()
        if not question or not answer:
            raise ValueError(f"{xml_path}: a qa_pair is missing its question or answer")
        pairs.append((question, answer))
    return pairs


def build(dataset_name: str) -> Path:
    folder = HERE / "datasets" / dataset_name
    pairs = read_pairs(folder / "evaluation.xml")
    out = folder / "examples" / f"{dataset_name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["query", "responses"])
        writer.writerows(pairs)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dataset-name", default="crosswalk-eval-0")
    args = parser.parse_args(argv)
    out = build(args.dataset_name)
    count = len(read_pairs(out.parent.parent / "evaluation.xml"))
    print(f"wrote {out} ({count} questions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
