#!/usr/bin/env python
"""Build the project site into _site/.

    uv run --no-project --with markdown python site/build.py

Two pages come out:

    index.html        the landing page, from site/index.template.html
    evaluation.html   eval/EVALUATION.md rendered as HTML

The result numbers on the landing page are computed here from the recorded
runs in eval/results, so the site cannot drift from the data. The GitHub
Actions workflow in .github/workflows/pages.yml runs this file and
publishes _site/ with GitHub Pages.
https://docs.github.com/en/pages/getting-started-with-github-pages
"""

from __future__ import annotations

import csv
import html
import re
import shutil
import statistics
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUT = ROOT / "_site"
RUNS = ROOT / "eval" / "results" / "2026-11-20" / "runs.csv"
REPO_URL = "https://github.com/gsa-mcp-hackathon/controls-crosswalk-mcp"

# The pages are styled with the U.S. Web Design System (USWDS), loaded from
# the jsDelivr CDN at one pinned version. Each integrity value is the hash of
# that exact file, so a browser refuses a file that has been changed. To move
# to a new version, change the number and recompute the three hashes.
# https://designsystem.digital.gov/documentation/developers/
# https://developer.mozilla.org/en-US/docs/Web/Security/Subresource_Integrity
USWDS = "https://cdn.jsdelivr.net/npm/@uswds/uswds@3.14.0/dist"
USWDS_CSS_HASH = (
    "sha384-CT3GOZ9N3YN8th26yjFq6WWlyXWwe5AaqH9zgBDcn0kyYcV9kZshYlFNXLuXdz2B"
)
USWDS_JS_HASH = (
    "sha384-lol3mZsCCEf0F2Sryzw870KbjAYgKOgHgYqrpWxPBN0uhXwXEwY3cSrS1u0aezLU"
)
USWDS_INIT_HASH = (
    "sha384-CYbI0QSQmY6lfiWjkejfJDcQnL0pmoqk2yk8LT8rsBqP4oqOkOoNSXc/9uG1IOvH"
)

PLACEHOLDER = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")


def load_runs() -> dict[str, list[dict]]:
    """The recorded runs, grouped by experiment name."""
    groups: dict[str, list[dict]] = {}
    with RUNS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            groups.setdefault(row["experiment"], []).append(row)
    return groups


def result_values(groups: dict[str, list[dict]]) -> dict[str, str]:
    """Every number the landing page shows, as text."""

    def correct(rows: list[dict]) -> int:
        return sum(row["correctness"] == "correct" for row in rows)

    def mean_seconds(rows: list[dict]) -> str:
        return f"{statistics.mean(float(row['seconds']) for row in rows):.1f}"

    v2 = groups["tools-prompt-v2"]
    v1 = groups["tools-prompt-v1"]
    base = groups["no-tools-baseline"]
    five = groups["tools-prompt-v2-five-runs"]
    calls = [int(row["tool_calls"]) for row in v2]
    data = [str(n) for n in range(1, 12)]  # the 11 questions answered from data
    total = len(v2)
    return {
        "total": str(total),
        "v2_correct": str(correct(v2)),
        "v1_correct": str(correct(v1)),
        "base_correct": str(correct(base)),
        "v2_percent": str(round(100 * correct(v2) / total)),
        "v1_percent": str(round(100 * correct(v1) / total)),
        "base_percent": str(round(100 * correct(base) / total)),
        "five_correct": str(correct(five)),
        "five_total": str(len(five)),
        "v2_seconds": mean_seconds(v2),
        "base_seconds": mean_seconds(base),
        "median_calls": str(int(statistics.median(calls))),
        "max_calls": str(max(calls)),
        "data_total": str(len(data)),
        "v1_data_correct": str(correct([r for r in v1 if r["question"] in data])),
        "base_data_correct": str(correct([r for r in base if r["question"] in data])),
        "run_count": str(sum(len(rows) for rows in groups.values())),
        "tool_run_count": str(len(v2) + len(v1) + len(five)),
    }


def uswds_values() -> dict[str, str]:
    """The USWDS tags for the page head and the end of the body."""
    head = (
        f'<script src="{USWDS}/js/uswds-init.min.js" integrity="{USWDS_INIT_HASH}"'
        ' crossorigin="anonymous"></script>\n'
        f'  <link rel="stylesheet" href="{USWDS}/css/uswds.min.css"'
        f' integrity="{USWDS_CSS_HASH}" crossorigin="anonymous">'
    )
    script = (
        f'<script src="{USWDS}/js/uswds.min.js" integrity="{USWDS_JS_HASH}"'
        ' crossorigin="anonymous"></script>'
    )
    return {"uswds_head": head, "uswds_script": script, "uswds_img": f"{USWDS}/img"}


def fill(template: str, values: dict[str, str]) -> str:
    """Replace {{name}} placeholders. An unknown name stops the build."""

    def swap(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise SystemExit(f"site: no value for placeholder {name!r}")
        return values[name]

    return PLACEHOLDER.sub(swap, template)


def render_evaluation() -> str:
    """eval/EVALUATION.md as an HTML fragment, with USWDS scrollable tables."""
    text = (ROOT / "eval" / "EVALUATION.md").read_text(encoding="utf-8")
    # The page template supplies the page heading.
    text = re.sub(r"\A# .*\n", "", text)
    # https://python-markdown.github.io/extensions/
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "toc"])
    # The summary table at the top has no column headings. Drop its empty
    # header row so screen readers do not announce blank headers.
    body = re.sub(r"<thead>\s*<tr>(\s*<th></th>)+\s*</tr>\s*</thead>", "", body)
    # https://designsystem.digital.gov/components/table/
    wrapper = '<div class="usa-table-container--scrollable" tabindex="0">'
    body = body.replace("<table>", wrapper + '<table class="usa-table">')
    return body.replace("</table>", "</table></div>")


def main() -> int:
    values = result_values(load_runs())
    values["repo_url"] = html.escape(REPO_URL, quote=True)
    values.update(uswds_values())

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copy(SITE / "style.css", OUT / "style.css")
    # Tell GitHub Pages to serve the files as they are, with no Jekyll step.
    # https://docs.github.com/en/pages/getting-started-with-github-pages/about-github-pages#static-site-generators
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    index = (SITE / "index.template.html").read_text(encoding="utf-8")
    (OUT / "index.html").write_text(fill(index, values), encoding="utf-8")

    page = (SITE / "page.template.html").read_text(encoding="utf-8")
    values["content"] = render_evaluation()
    (OUT / "evaluation.html").write_text(fill(page, values), encoding="utf-8")

    print(f"site written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
