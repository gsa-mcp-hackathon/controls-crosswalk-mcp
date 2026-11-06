"""Load the CPRT export of CSF 2.0 into store rows.

The export holds the CSF 2.0 core: six functions, their categories, and the
subcategories under each, with implementation examples. It also keeps the
CSF 1.1 identifiers that CSF 2.0 retired, each with a note saying where its
content went. The store labels those "legacy" rather than "withdrawn",
because CSF 2.0 never published them; they are kept so an old identifier
can still be looked up.

Edges in the export:

    function -> category -> subcategory -> implementation_example
                                        -> party (1st or 3rd party risk tag)
    element -> sort, withdraw_reason
    withdraw_reason -> element          (incorporated_into, moved_to)
    category or subcategory -> family   (external_reference to SP 800-53)

The informative references to SP 800-53 point at families (IA, AC), not at
controls, and name release 5.1.1 as their target. The loader keeps them
exactly that way. CPRT documentation: https://csrc.nist.gov/projects/cprt
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from crosswalk_mcp.ids import normalize_csf_id
from crosswalk_mcp.loaders.common import natural_key
from crosswalk_mcp.loaders.sp800_53 import LoaderError

ELEMENT_KINDS = ("function", "category", "subcategory")


@dataclass
class CsfRows:
    """Rows for every csf_* table, keyed by the table's short name."""

    document: dict
    elements: list[dict] = field(default_factory=list)
    examples: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)
    tags: list[dict] = field(default_factory=list)


def load(payload: dict, source_key: str, source_sha256: str) -> CsfRows:
    """Parse the CPRT CSF 2.0 export and return rows for the store."""
    try:
        body = payload["response"]["elements"]
        document = body["documents"][0]
    except (KeyError, IndexError, TypeError):
        raise LoaderError(
            "not a CPRT framework export (missing response.elements)"
        ) from None

    by_id: dict[str, dict] = {}
    for element in body["elements"]:
        by_id.setdefault(element["element_identifier"], element)

    projections: dict[str, list[str]] = defaultdict(list)
    edges: list[tuple[str, str, str]] = []
    references: list[tuple[str, str, str]] = []
    for rel in body["relationships"]:
        src = rel["source_element_identifier"]
        dst = rel["dest_element_identifier"]
        kind = rel["relationship_identifier"]
        if kind == "projection":
            if dst not in projections[src]:
                projections[src].append(dst)
        elif kind == "external_reference":
            references.append((src, dst, rel["dest_doc_identifier"]))
        else:
            edges.append((src, dst, kind))

    rows = CsfRows(
        document={
            "doc_identifier": document["doc_identifier"],
            "name": document["name"],
            "version": " ".join(document["version"].split()),
            "website": document["website"],
            "source_key": source_key,
            "source_sha256": source_sha256,
        }
    )

    def kind_of(ident: str) -> str | None:
        element = by_id.get(ident)
        return element["element_type"] if element else None

    element_ids: set[str] = set()
    for element in body["elements"]:
        if element["element_type"] not in ELEMENT_KINDS:
            continue
        ident = element["element_identifier"]
        element_ids.add(ident)
        sort_elements = [
            by_id[dst] for dst in projections.get(ident, []) if kind_of(dst) == "sort"
        ]
        legacy_note = ""
        for dst in projections.get(ident, []):
            if kind_of(dst) == "withdraw_reason":
                legacy_note = by_id[dst]["text"].strip()
        rows.elements.append(
            {
                "id": ident,
                "kind": element["element_type"],
                "parent_id": parent_of(ident),
                "function_id": ident[:2],
                "title": element["title"].strip(),
                "text": " ".join(element["text"].split()),
                "sort_key": sort_elements[0]["title"] if sort_elements else "",
                "legacy": 1 if legacy_note else 0,
                "legacy_note": legacy_note or None,
            }
        )

        examples = sorted(
            (
                dst
                for dst in projections.get(ident, [])
                if kind_of(dst) == "implementation_example"
            ),
            key=natural_key,
        )
        for position, example_id in enumerate(examples):
            example = by_id[example_id]
            rows.examples.append(
                {
                    "element_id": ident,
                    "id": example_id,
                    "label": example["title"].strip(),
                    "text": " ".join(example["text"].split()),
                    "position": position,
                }
            )

        for dst in projections.get(ident, []):
            if kind_of(dst) == "party":
                party = by_id[dst]
                rows.tags.append(
                    {
                        "element_id": ident,
                        "tag": party["element_identifier"],
                        "label": party["text"].strip(),
                    }
                )

    # Where retired identifiers went. The edge starts at the withdraw reason
    # element (WR-ID.BE-02), which we attribute back to its element.
    for src, dst, kind in edges:
        source_id = src[3:] if src.startswith("WR-") else src
        if source_id not in element_ids or dst not in element_ids:
            continue
        rows.relations.append({"source_id": source_id, "dest_id": dst, "kind": kind})

    for src, dst, target_doc in references:
        if src not in element_ids:
            continue
        rows.references.append(
            {"element_id": src, "target_doc": target_doc, "target_id": dst}
        )
    return rows


def parent_of(ident: str) -> str | None:
    """The category of a subcategory, the function of a category, else None.

    The identifier carries its own ancestry: GV.OC-01 sits in GV.OC, which
    sits in GV. The normalizer also rejects anything that is not a CSF id.
    """
    normalized = normalize_csf_id(ident)
    if "-" in normalized:
        return normalized.split("-", 1)[0]
    if "." in normalized:
        return normalized.split(".", 1)[0]
    return None
