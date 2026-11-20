"""controls_crosswalk: follow published links between frameworks.

Two published link sets exist in the store:

- CSF 2.0 informative references, from a category or subcategory to an
  SP 800-53 family (publisher NIST, target release 5.1.1).
- FedRAMP "Related SP 800-53 Controls", from a KSI indicator to a control
  (publisher FedRAMP, no release named).

A result is "direct" when it is one of those links read in either
direction. It is "derived" when the tool composed links, or when it had to
step from a control to its family to use a family level link. Every hit
shows the path it took and labels each link, so a reader can judge the
evidence rather than trust a score. Nothing here says a requirement is met.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from crosswalk_mcp.ids import IdKind, InvalidIdentifier, classify, normalize_id
from crosswalk_mcp.models import LATEST_RELEASE, Framework, PaginationParams
from crosswalk_mcp.store import CSF_SOURCE, FEDRAMP_SOURCE, SP800_53_RELEASES, Store
from crosswalk_mcp.tools.common import (
    cprt_citation,
    csf_citation,
    get_store,
    ksi_citation,
    snapshot_provenance,
    source_record,
)

KIND_TO_FRAMEWORK = {
    IdKind.CONTROL: Framework.SP800_53,
    IdKind.CSF: Framework.CSF,
    IdKind.KSI: Framework.KSI,
}

DERIVED_NOTE = (
    "Derived hits compose published links through SP 800-53 family "
    "membership. They are a starting point for analysis, not a published "
    "mapping."
)
FAMILY_NOTE = (
    "The CPRT export of CSF 2.0 gives its SP 800-53 references at the family "
    "level. Use controls_search with the family filter, or "
    "controls_get_baseline, to list the controls in a family."
)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="controls_crosswalk",
        annotations={
            "title": "Crosswalk between SP 800-53, CSF 2.0, and FedRAMP KSIs",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def controls_crosswalk(
        source_id: Annotated[
            str,
            Field(
                description=(
                    "Where to start: an SP 800-53 control (AC-2, ac-2.3), a CSF "
                    "2.0 category or subcategory (PR.AA, PR.AA-01), or a FedRAMP "
                    "KSI indicator (KSI-IAM-AAM)."
                )
            ),
        ],
        to_framework: Annotated[
            Framework,
            Field(description="Which framework to arrive at: sp800_53, csf, or ksi."),
        ],
        max_hops: Annotated[
            int,
            Field(
                ge=1,
                le=2,
                description=(
                    "How many published links a derived path may chain. 1 keeps "
                    "to single links; 2 also allows CSF to KSI paths through "
                    "SP 800-53."
                ),
            ),
        ] = 2,
        pagination: PaginationParams | None = None,
    ) -> dict:
        """Follow the published relationships from one identifier into
        another framework, and report what was found with its evidence.

        Direct hits are single published links: a CSF element's informative
        reference to an SP 800-53 family, or a FedRAMP KSI's related control.
        Derived hits are composed through SP 800-53 family membership, for
        example CSF to family to control to KSI, and are labeled as such.
        Each hit carries its full path, every link's publisher and
        direction, and a citation. A result with no hits means no published
        link exists in these sources, which is not a statement about
        implementation.
        """
        store = get_store()
        kind, ident = _resolve(source_id)
        if kind == to_framework:
            raise ToolError(
                f"{ident} is already in {to_framework.value}. Pick a different "
                "to_framework, or use controls_get_control for related controls."
            )
        page = pagination or PaginationParams()
        with store.lock:
            view = _CrosswalkView(store, ident, kind, to_framework, max_hops)
            result = view.run()
        derived = result["derived"]
        window = derived[page.offset : page.offset + page.limit]
        next_offset = page.offset + len(window)
        result["derived"] = {
            "total": len(derived),
            "count": len(window),
            "offset": page.offset,
            "has_more": next_offset < len(derived),
            "next_offset": next_offset if next_offset < len(derived) else None,
            "items": window,
        }
        return result


def _resolve(raw: str) -> tuple[Framework, str]:
    """The framework and normalized id of the starting point, or a ToolError
    that says which identifiers the tool accepts."""
    if re.fullmatch(r"\s*[A-Za-z]{2}\s*", raw or ""):
        raise ToolError(
            f"'{raw.strip()}' is a bare two letter code, which could be an "
            "SP 800-53 family or a CSF function. Neither has published "
            "references. Use controls_search with the family filter for "
            "controls, or controls_get_csf_element to list a function's "
            "categories, then crosswalk a category or subcategory."
        )
    try:
        kind = classify(raw)
    except InvalidIdentifier:
        raise ToolError(
            f"'{raw}' is not an identifier this tool accepts. Use an SP 800-53 "
            "control such as AC-2, a CSF 2.0 category or subcategory such as "
            "PR.AA-01, or a FedRAMP KSI indicator such as KSI-IAM-AAM."
        ) from None
    if kind not in KIND_TO_FRAMEWORK:
        raise ToolError(
            f"'{raw}' looks like an SP 800-171 requirement, which this server "
            "does not hold. Use an SP 800-53 control, a CSF 2.0 element, or a "
            "FedRAMP KSI indicator."
        )
    _, ident = normalize_id(raw)
    if kind is IdKind.KSI and ident.count("-") == 1:
        raise ToolError(
            f"{ident} is a KSI theme. Use controls_get_ksi with {ident} to list "
            "its indicators, then crosswalk one indicator."
        )
    return KIND_TO_FRAMEWORK[kind], ident


class _CrosswalkView:
    """One crosswalk request. Caller holds the store lock."""

    def __init__(
        self, store: Store, ident: str, kind: Framework, target: Framework, hops: int
    ):
        self.store = store
        self.ident = ident
        self.kind = kind
        self.target = target
        self.hops = hops
        self.release = LATEST_RELEASE.value
        self.notes: list[str] = []
        self.sources: set[str] = set()
        self.csf_document = store.csf_document()
        self.fedramp_document = store.fedramp_document()
        self.fedramp_url = source_record(store, FEDRAMP_SOURCE)["url"]

    def run(self) -> dict:
        source = self._source_record()
        handlers = {
            (Framework.SP800_53, Framework.CSF): self._control_to_csf,
            (Framework.SP800_53, Framework.KSI): self._control_to_ksi,
            (Framework.CSF, Framework.SP800_53): self._csf_to_controls,
            (Framework.CSF, Framework.KSI): self._csf_to_ksi,
            (Framework.KSI, Framework.SP800_53): self._ksi_to_controls,
            (Framework.KSI, Framework.CSF): self._ksi_to_csf,
        }
        direct, derived = handlers[(self.kind, self.target)](source)
        if not direct and not derived:
            self.notes.append(
                f"No published link from {self.ident} to {self.target.value} "
                "exists in these sources. That is a gap in the published "
                "mappings, not a statement about implementation."
            )
        if derived:
            self.notes.append(DERIVED_NOTE)
        return {
            "source": source,
            "to_framework": self.target.value,
            "max_hops": self.hops,
            "direct": direct,
            "derived": derived,
            "notes": self.notes,
            "provenance": {
                **snapshot_provenance(self.store),
                "catalog_release": self.release,
                "sources": [
                    source_record(self.store, key) for key in sorted(self.sources)
                ],
            },
        }

    # Starting points.

    def _source_record(self) -> dict:
        if self.kind is Framework.SP800_53:
            brief = self.store.control_briefs([self.ident], self.release).get(
                self.ident
            )
            if brief is None:
                raise ToolError(
                    f"{self.ident} is not in SP 800-53 release {self.release}. "
                    "Check the id with controls_get_control."
                )
            self.control = brief
            return {
                "framework": "sp800_53",
                "id": self.ident,
                "title": brief["title"],
                "family": brief["family"],
                "withdrawn": brief["withdrawn"],
            }
        if self.kind is Framework.CSF:
            record = self.store.get_csf_element(self.ident)
            if record is None:
                raise ToolError(
                    f"{self.ident} is not in CSF 2.0 or in the retired CSF 1.1 "
                    "identifiers CPRT keeps. Check it with "
                    "controls_get_csf_element."
                )
            self.csf_element = record
            if record["legacy"]:
                self.notes.append(
                    f"{self.ident} is a retired CSF 1.1 identifier with no "
                    f"published references: {record['legacy_note']}. Crosswalk "
                    "the identifiers it was incorporated into or moved to."
                )
            return {
                "framework": "csf",
                "id": self.ident,
                "kind": record["kind"],
                "title": record["title"] or record["text"],
                "status": "legacy" if record["legacy"] else "active",
            }
        record = self.store.get_ksi(self.ident)
        if record is None:
            raise ToolError(
                f"{self.ident} is not a KSI in the FedRAMP rules this server "
                "holds. Check it with controls_get_ksi."
            )
        self.ksi = record
        return {
            "framework": "ksi",
            "id": self.ident,
            "title": record["name"],
            "theme_id": record["theme_id"],
        }

    # Link records. direction says whether the link was read the way its
    # publisher wrote it or backwards.

    def _csf_link(
        self, element_id: str, family: str, direction: str, target_doc: str
    ) -> dict:
        self.sources.add(CSF_SOURCE)
        return {
            "from": element_id,
            "to": family,
            "type": "informative_reference",
            "publisher": "NIST",
            "level": "family",
            "catalog_release": self.store.release_for_document(target_doc)
            or "unspecified",
            "direction": direction,
            "source": CSF_SOURCE,
        }

    def _ksi_link(self, indicator_id: str, control_id: str, direction: str) -> dict:
        self.sources.add(FEDRAMP_SOURCE)
        return {
            "from": indicator_id,
            "to": control_id,
            "type": "related_control",
            "publisher": "FedRAMP",
            "level": "control",
            "catalog_release": "unspecified",
            "direction": direction,
            "source": FEDRAMP_SOURCE,
        }

    def _family_step(self, control_id: str, family: str) -> dict:
        """Not a published link: a control belongs to its family."""
        self.sources.add(SP800_53_RELEASES[0][1])
        return {
            "from": control_id,
            "to": family,
            "type": "family_membership",
            "publisher": "NIST",
            "level": "control",
            "catalog_release": self.release,
            "direction": "structural",
            "source": SP800_53_RELEASES[0][1],
        }

    # Hit records for each framework.

    def _control_hit(self, brief: dict) -> dict:
        return {
            "framework": "sp800_53",
            "id": brief["id"],
            "title": brief["title"],
            "withdrawn": brief["withdrawn"],
            "citation": cprt_citation(
                self.store, self.release, brief["cprt_id"], brief["title"]
            ),
        }

    def _family_hit(self, family: str, title: str | None) -> dict:
        return {"framework": "sp800_53", "id": family, "kind": "family", "title": title}

    def _csf_hit(self, row: dict) -> dict:
        return {
            "framework": "csf",
            "id": row["id"],
            "kind": row["kind"],
            "title": row["title"] or row["text"],
            "status": "legacy" if row["legacy"] else "active",
            "citation": csf_citation(self.csf_document, row),
        }

    def _ksi_hit(self, row: dict) -> dict:
        return {
            "framework": "ksi",
            "id": row["id"],
            "title": row["name"],
            "theme_id": row["theme_id"],
            "citation": ksi_citation(self.fedramp_document, self.fedramp_url, row),
        }

    # The six crosswalk shapes. Each returns (direct, derived).

    def _control_to_csf(self, source: dict):
        family = self.control["family"]
        derived = []
        for row in self.store.csf_elements_for_families([family]):
            derived.append(
                {
                    **self._csf_hit(row),
                    "relationship": "derived",
                    "hops": 1,
                    "path": [self.ident, family, row["id"]],
                    "links": [
                        self._family_step(self.ident, family),
                        self._csf_link(row["id"], family, "reverse", row["target_doc"]),
                    ],
                }
            )
        if derived:
            self.notes.append(
                f"CSF references name the {family} family, not {self.ident} "
                "itself, so every CSF element that references the family is "
                "listed."
            )
        return [], derived

    def _control_to_ksi(self, source: dict):
        direct = [
            {
                **self._ksi_hit(row),
                "relationship": "direct",
                "hops": 1,
                "path": [self.ident, row["id"]],
                "links": [self._ksi_link(row["id"], self.ident, "reverse")],
            }
            for row in self.store.ksis_for_controls([self.ident])
        ]
        return direct, []

    def _csf_to_controls(self, source: dict):
        families = self._csf_families()
        titles = self.store.family_titles(self.release)
        direct = [
            {
                **self._family_hit(family, titles.get(family)),
                "relationship": "direct",
                "hops": 1,
                "path": [self.ident, family],
                "links": [
                    self._csf_link(self.ident, family, "as_published", target_doc)
                ],
            }
            for family, target_doc in families
        ]
        if direct:
            self.notes.append(FAMILY_NOTE)
        return direct, []

    def _csf_to_ksi(self, source: dict):
        if self.hops < 2:
            self.notes.append(
                "CSF to KSI paths need two published links. Set max_hops to 2."
            )
            return [], []
        families = self._csf_families()
        family_of: dict[str, str] = {}
        target_docs: dict[str, str] = dict(families)
        for family, _ in families:
            for control in self.store.controls_in_family(family, self.release):
                family_of[control["id"]] = family
        grouped: dict[str, dict] = {}
        for row in self.store.ksis_for_controls(list(family_of)):
            control_id = row["control_id"]
            family = family_of[control_id]
            target_doc = target_docs[family]
            hit = grouped.get(row["id"])
            if hit is None:
                hit = grouped[row["id"]] = {
                    **self._ksi_hit(row),
                    "relationship": "derived",
                    "hops": 2,
                    "path": [self.ident, family, control_id, row["id"]],
                    "links": [
                        self._csf_link(self.ident, family, "as_published", target_doc),
                        self._family_step(control_id, family),
                        self._ksi_link(row["id"], control_id, "reverse"),
                    ],
                    "via": {"families": [], "controls": []},
                }
            if family not in hit["via"]["families"]:
                hit["via"]["families"].append(family)
            hit["via"]["controls"].append(control_id)
        return [], list(grouped.values())

    def _ksi_to_controls(self, source: dict):
        ids = [c["id"] for c in self.ksi["controls"]]
        briefs = self.store.control_briefs(ids, self.release)
        direct = []
        for control in self.ksi["controls"]:
            brief = briefs.get(control["id"])
            hit = (
                self._control_hit(brief)
                if brief
                else {
                    "framework": "sp800_53",
                    "id": control["id"],
                    "title": None,
                    "withdrawn": None,
                    "citation": None,
                }
            )
            direct.append(
                {
                    **hit,
                    "relationship": "direct",
                    "hops": 1,
                    "path": [self.ident, control["id"]],
                    "links": [
                        self._ksi_link(self.ident, control["id"], "as_published")
                    ],
                }
            )
        missing = [h["id"] for h in direct if h["title"] is None]
        if missing:
            self.notes.append(
                f"Not in SP 800-53 release {self.release}: {', '.join(missing)}. "
                "Reported as published."
            )
        return direct, []

    def _ksi_to_csf(self, source: dict):
        if self.hops < 2:
            self.notes.append(
                "KSI to CSF paths need two published links. Set max_hops to 2."
            )
            return [], []
        ids = [c["id"] for c in self.ksi["controls"]]
        briefs = self.store.control_briefs(ids, self.release)
        controls_by_family: dict[str, list[str]] = {}
        for control_id in ids:
            brief = briefs.get(control_id)
            if brief:
                controls_by_family.setdefault(brief["family"], []).append(control_id)
        grouped: dict[str, dict] = {}
        for row in self.store.csf_elements_for_families(list(controls_by_family)):
            family = row["family"]
            hit = grouped.get(row["id"])
            if hit is None:
                first = controls_by_family[family][0]
                hit = grouped[row["id"]] = {
                    **self._csf_hit(row),
                    "relationship": "derived",
                    "hops": 2,
                    "path": [self.ident, first, family, row["id"]],
                    "links": [
                        self._ksi_link(self.ident, first, "as_published"),
                        self._family_step(first, family),
                        self._csf_link(row["id"], family, "reverse", row["target_doc"]),
                    ],
                    "via": {"families": [], "controls": []},
                }
            hit["via"]["families"].append(family)
            for control_id in controls_by_family[family]:
                if control_id not in hit["via"]["controls"]:
                    hit["via"]["controls"].append(control_id)
        return [], list(grouped.values())

    def _csf_families(self) -> list[tuple[str, str]]:
        """The families the source CSF element references, each with the
        SP 800-53 document the reference names."""
        return [
            (ref["target_id"], ref["target_doc"])
            for ref in self.csf_element["references"]
        ]
