"""trace_relationships: follow published links out from one identifier.

The prompt tells the model to look up the starting point first, then
crosswalk into each other framework, and to keep direct and derived hits
apart when it reports.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

STEPS = """Work through these steps and use only what the tools return:

1. Look up the starting point so you can describe it: controls_get_control
   for an SP 800-53 control, controls_get_csf_element for a CSF 2.0 element,
   or controls_get_ksi for a FedRAMP Key Security Indicator. If the id is a
   CSF function or a KSI theme, list its children and ask which one to trace.
2. Call controls_crosswalk once for each other framework (sp800_53, csf,
   ksi) with max_hops 2. Page through derived results if has_more is true.
3. If the starting point is a control, also call controls_baseline_membership
   for it.

Then write the trace:

- Describe the starting point in one or two sentences, quoting its published
  text.
- Report direct hits first. For each, name the publisher, the direction the
  link was read in, and the catalog release the link names.
- Report derived hits in their own section, say that they are composed
  through SP 800-53 family membership, and show the path for each.
- When a tool reports no published link, say that plainly as a gap in the
  published mappings.
- Give the citation URL for every hit and end with the snapshot hash from
  provenance.

Do not say whether any organization meets a control or indicator. Do not
invent relationships the tools did not report. If a tool returns an error,
say what it said and stop."""


def register(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="trace_relationships",
        title="Trace published relationships from one identifier",
        description=(
            "Look up an SP 800-53 control, a CSF 2.0 element, or a FedRAMP KSI, "
            "then follow the published links into the other frameworks and "
            "report direct and derived relationships separately."
        ),
    )
    def trace_relationships(
        identifier: Annotated[
            str,
            Field(
                description=(
                    "Where to start: a control such as AC-2, a CSF subcategory "
                    "such as PR.AA-01, or a KSI such as KSI-IAM-AAM."
                )
            ),
        ],
    ) -> str:
        """Trace the published relationships from one identifier."""
        opening = (
            f"Trace the published relationships that start from {identifier.strip()}."
        )
        return opening + "\n\n" + STEPS
