"""Load one CPRT export of SP 800-53 into store rows.

The CPRT export is a flat list of elements plus a list of relationships.
A control is connected to everything it owns through "projection" edges:

    control -> control_statement (root) -> control_statement (items)
                                        -> determination (objective) -> odp
            -> discussion, examine, interview, test, reference
            -> security_baseline, privacy_baseline, sort, withdraw_reason
            -> control_enhancement

Cross control edges use the other relationship types: "related",
"incorporated_into", and "moved_to". CPRT documentation:
https://csrc.nist.gov/projects/cprt
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field

from crosswalk_mcp.ids import parse_control_id
from crosswalk_mcp.loaders.common import html_to_text, natural_key

CONTROL_TYPES = {"control", "control_enhancement"}

# CPRT baseline element ids -> the baseline names the store uses.
SECURITY_BASELINES = {"SB-Low": "low", "SB-Moderate": "moderate", "SB-High": "high"}
PRIVACY_BASELINES = {"PB-Yes": "privacy"}

# CPRT parameter types -> plain names. "single_entry" is an Assignment,
# the others are Selection (one) and Selection (one or more).
PARAMETER_KINDS = {
    "single_entry": "assignment",
    "single_select": "selection_one",
    "multi_select": "selection_many",
}


class LoaderError(ValueError):
    """The export did not have the shape this loader expects."""


@dataclass
class Rows:
    """Rows for every store table this loader fills, keyed by table name."""

    release: dict
    families: list[dict] = field(default_factory=list)
    controls: list[dict] = field(default_factory=list)
    statements: list[dict] = field(default_factory=list)
    objectives: list[dict] = field(default_factory=list)
    parameters: list[dict] = field(default_factory=list)
    assessment_methods: list[dict] = field(default_factory=list)
    control_references: list[dict] = field(default_factory=list)
    control_relations: list[dict] = field(default_factory=list)
    cprt_baselines: list[dict] = field(default_factory=list)


class _Graph:
    """Index of the export: elements by id and projection edges by source."""

    def __init__(self, body: dict):
        self.by_id: dict[str, list[dict]] = defaultdict(list)
        for element in body["elements"]:
            self.by_id[element["element_identifier"]].append(element)
        # Parameters grouped by the control they belong to, from the id
        # prefix: AC-02_ODP[01] belongs to AC-02.
        self.odps_by_control: dict[str, list[dict]] = defaultdict(list)
        for element in body["elements"]:
            if (
                element["element_type"] == "odp"
                and "_ODP" in element["element_identifier"]
            ):
                prefix = element["element_identifier"].split("_ODP", 1)[0]
                self.odps_by_control[prefix].append(element)
        self.projections: dict[str, list[str]] = defaultdict(list)
        self.edges: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for rel in body["relationships"]:
            src = rel["source_element_identifier"]
            dst = rel["dest_element_identifier"]
            kind = rel["relationship_identifier"]
            if kind == "projection":
                if (src, dst) not in seen:
                    seen.add((src, dst))
                    self.projections[src].append(dst)
            else:
                self.edges.append((src, dst, kind))

    def typed(self, ident: str, element_type: str) -> list[dict]:
        return [
            e for e in self.by_id.get(ident, []) if e["element_type"] == element_type
        ]

    def children(self, ident: str, element_type: str) -> list[str]:
        """Projection targets of ident that have the given element type."""
        return [
            dst
            for dst in self.projections.get(ident, [])
            if self.typed(dst, element_type)
        ]

    def first_text(self, ident: str, element_type: str) -> str:
        found = self.typed(ident, element_type)
        return found[0]["text"] if found else ""


def load(payload: dict, release: str, source_key: str, source_sha256: str) -> Rows:
    """Parse one CPRT 800-53 export and return rows for the store."""
    try:
        body = payload["response"]["elements"]
        document = body["documents"][0]
    except (KeyError, IndexError, TypeError):
        raise LoaderError(
            "not a CPRT framework export (missing response.elements)"
        ) from None

    graph = _Graph(body)
    rows = Rows(
        release={
            "release": release,
            "doc_identifier": document["doc_identifier"],
            "name": document["name"],
            "version": document["version"],
            "website": document["website"],
            "source_key": source_key,
            "source_sha256": source_sha256,
        }
    )

    family_titles = {
        e["element_identifier"]: e["title"].strip()
        for e in body["elements"]
        if e["element_type"] == "family"
    }
    for family_id, title in sorted(family_titles.items()):
        rows.families.append({"release": release, "id": family_id, "title": title})

    control_ids: set[str] = set()
    for element in body["elements"]:
        if element["element_type"] not in CONTROL_TYPES:
            continue
        cprt_id = element["element_identifier"]
        if cprt_id in control_ids:
            continue
        control_ids.add(cprt_id)
        _load_control(graph, element, release, rows)

    # Cross control edges. The source of a withdrawal edge is the withdraw
    # reason element (WR-AC-13), which we attribute back to its control.
    for src, dst, kind in graph.edges:
        source_id = src[3:] if src.startswith("WR-") else src
        if source_id not in control_ids or dst not in control_ids:
            continue
        rows.control_relations.append(
            {
                "release": release,
                "source_id": parse_control_id(source_id).canonical,
                "dest_id": parse_control_id(dst).canonical,
                "kind": kind,
            }
        )
    return rows


def _load_control(graph: _Graph, element: dict, release: str, rows: Rows) -> None:
    cprt_id = element["element_identifier"]
    parsed = parse_control_id(cprt_id)
    control_id = parsed.canonical
    parent_id = parsed.base.canonical if parsed.is_enhancement else None

    withdraw_reason = graph.first_text(f"WR-{cprt_id}", "withdraw_reason").strip()
    sort_elements = graph.typed(f"S-{cprt_id}", "sort")
    sort_key = sort_elements[0]["title"] if sort_elements else ""

    statement_roots = graph.children(cprt_id, "control_statement")
    statement_lines: list[str] = []
    seen_parameters: dict[str, dict] = {}
    for root in statement_roots:
        _load_statements(
            graph,
            root,
            None,
            0,
            control_id,
            release,
            rows,
            statement_lines,
            seen_parameters,
        )
    # Some parameters are only referenced from objectives we did not reach,
    # so also pick up anything that carries the control's own prefix.
    for ident, elements in graph.by_id.items():
        if ident.startswith(f"{cprt_id}_ODP") and ident not in seen_parameters:
            for odp in elements:
                if odp["element_type"] == "odp":
                    seen_parameters[ident] = _parameter_row(
                        graph, odp, control_id, release
                    )
                    break
    for ident in sorted(seen_parameters, key=natural_key):
        rows.parameters.append(seen_parameters[ident])

    for method in ("examine", "interview", "test"):
        text = graph.first_text(f"{method[0].upper()}-{cprt_id}", method).strip()
        if text:
            rows.assessment_methods.append(
                {
                    "release": release,
                    "control_id": control_id,
                    "method": method,
                    "text": text,
                }
            )

    seen_refs: set[tuple[str, str]] = set()
    for ref_id in graph.projections.get(cprt_id, []):
        for ref in graph.typed(ref_id, "reference"):
            key = (ref["title"].strip(), ref["text"].strip())
            if key in seen_refs:
                continue
            seen_refs.add(key)
            rows.control_references.append(
                {
                    "release": release,
                    "control_id": control_id,
                    "title": key[0],
                    "url": key[1],
                }
            )

    privacy = False
    for dst in graph.projections.get(cprt_id, []):
        if dst in SECURITY_BASELINES:
            rows.cprt_baselines.append(
                {
                    "release": release,
                    "control_id": control_id,
                    "baseline": SECURITY_BASELINES[dst],
                }
            )
        elif dst in PRIVACY_BASELINES:
            privacy = True
            rows.cprt_baselines.append(
                {
                    "release": release,
                    "control_id": control_id,
                    "baseline": PRIVACY_BASELINES[dst],
                }
            )

    rows.controls.append(
        {
            "release": release,
            "id": control_id,
            "cprt_id": cprt_id,
            "oscal_id": parsed.oscal,
            "family": parsed.family,
            "parent_id": parent_id,
            "title": element["title"].strip(),
            "sort_key": sort_key,
            "withdrawn": 1 if withdraw_reason else 0,
            "withdraw_reason": withdraw_reason or None,
            "statement_text": "\n".join(statement_lines).strip(),
            "discussion": html_to_text(graph.first_text(f"D-{cprt_id}", "discussion")),
            "privacy_baseline": 1 if privacy else 0,
        }
    )


def _load_statements(
    graph: _Graph,
    ident: str,
    parent: str | None,
    depth: int,
    control_id: str,
    release: str,
    rows: Rows,
    lines: list[str],
    parameters: dict[str, dict],
) -> None:
    element = graph.typed(ident, "control_statement")[0]
    label = element["title"].strip()
    text = element["text"].strip()
    rows.statements.append(
        {
            "release": release,
            "control_id": control_id,
            "id": ident,
            "parent_id": parent,
            "label": label or None,
            "text": text,
            "depth": depth,
            "position": len(rows.statements),
        }
    )
    if text:
        prefix = f"{label}. " if label else ""
        lines.append(f"{'  ' * depth}{prefix}{text}")

    objective_ids = sorted(graph.children(ident, "determination"), key=natural_key)
    for objective_id in objective_ids:
        for objective in graph.typed(objective_id, "determination"):
            parameter_ids = sorted(graph.children(objective_id, "odp"), key=natural_key)
            for parameter_id in parameter_ids:
                if parameter_id not in parameters:
                    odp = graph.typed(parameter_id, "odp")[0]
                    parameters[parameter_id] = _parameter_row(
                        graph, odp, control_id, release
                    )
            rows.objectives.append(
                {
                    "release": release,
                    "control_id": control_id,
                    "id": objective_id,
                    "statement_id": ident,
                    "text": objective["text"].strip(),
                    "parameter_ids": json.dumps(parameter_ids),
                    "position": len(rows.objectives),
                }
            )

    children = sorted(
        graph.children(ident, "control_statement"),
        key=lambda child: natural_key(
            graph.typed(child, "control_statement")[0]["title"]
        ),
    )
    for child in children:
        _load_statements(
            graph, child, ident, depth + 1, control_id, release, rows, lines, parameters
        )


def _parameter_row(graph: _Graph, odp: dict, control_id: str, release: str) -> dict:
    ident = odp["element_identifier"]
    kind = "assignment"
    statement = ""
    for dst in graph.projections.get(ident, []):
        if dst in PARAMETER_KINDS:
            kind = PARAMETER_KINDS[dst]
        elif graph.typed(dst, "odp_statement"):
            statement = graph.first_text(dst, "odp_statement").strip()
    choices = None
    if kind != "assignment" and statement:
        choices = json.dumps([c.strip() for c in statement.split(";") if c.strip()])
    return {
        "release": release,
        "control_id": control_id,
        "id": ident,
        "label": odp["title"].strip(),
        "guideline": odp["text"].strip(),
        "kind": kind,
        "statement": statement or None,
        "choices": choices,
    }
