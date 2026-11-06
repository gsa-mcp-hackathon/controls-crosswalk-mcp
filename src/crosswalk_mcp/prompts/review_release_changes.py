"""review_release_changes: walk an analyst through an SP 800-53 update.

The prompt is a user message that tells the model which tools to call and
in what order, and how to present what it finds. It never asks the model
to judge whether a control is implemented.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

STEPS = """Work through these steps and use only what the tools return:

1. Call controls_diff_releases with from_release "{older}" and to_release
   "{newer}". Pass the scope as control_id if it is a control, as family if
   it is a family, or leave both unset for the whole catalog. For a family or
   the catalog, page through the changed list if has_more is true.
2. For each changed control that matters, call controls_diff_releases again
   with that control_id to see the exact wording changes. Separate
   requirement changes (statement, parameters, objectives, assessment
   methods) from discussion edits and new related control links.
3. For every added or changed control, call controls_baseline_membership to
   say which SP 800-53B baselines select it, so the reader knows who is
   affected.
4. For each changed control, check the fedramp section from
   controls_get_control to note any FedRAMP Key Security Indicators that
   name it.

Then write the review:

- Start with the counts: added, removed, changed, unchanged.
- List requirement changes first, quoting the before and after text the
  tool returned.
- List discussion only changes and relation only changes briefly.
- For each item, give the baselines it belongs to and the citation URL from
  the provenance block.
- End with the snapshot hash from provenance so the review can be
  reproduced.

Do not say whether any organization meets a control. Do not add controls or
changes the tools did not report. If a tool returns an error, say what it
said and stop."""


def register(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="review_release_changes",
        title="Review what changed between SP 800-53 releases",
        description=(
            "Summarize the changes between two SP 800-53 releases for the whole "
            "catalog, one family, or one control, with citations and baseline "
            "impact."
        ),
    )
    def review_release_changes(
        scope: Annotated[
            str,
            Field(
                description=(
                    "What to review: a family such as SI, a control such as "
                    "SI-7(12), or blank for the whole catalog."
                )
            ),
        ] = "",
        from_release: Annotated[
            str, Field(description="Older release, for example 5.1.1.")
        ] = "5.1.1",
        to_release: Annotated[
            str, Field(description="Newer release, for example 5.2.0.")
        ] = "5.2.0",
    ) -> str:
        """Review the differences between two SP 800-53 releases."""
        target = scope.strip() or "the whole catalog"
        opening = (
            f"Review the changes in NIST SP 800-53 between release {from_release} "
            f"and release {to_release} for {target}."
        )
        return opening + "\n\n" + STEPS.format(older=from_release, newer=to_release)
