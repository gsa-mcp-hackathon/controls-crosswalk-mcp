"""Load one OSCAL resolved baseline catalog into store rows.

NIST publishes SP 800-53B as OSCAL profiles and also as "resolved" catalogs
that list every control the baseline selects. The resolved form is what we
read: each control that appears in it is a member of the baseline.
https://github.com/usnistgov/oscal-content
"""

from __future__ import annotations

from dataclasses import dataclass, field

from crosswalk_mcp.ids import parse_control_id
from crosswalk_mcp.loaders.sp800_53 import LoaderError


@dataclass
class BaselineRows:
    baseline: dict
    members: list[dict] = field(default_factory=list)


def load(
    payload: dict, baseline: str, source_key: str, source_sha256: str
) -> BaselineRows:
    """Parse one resolved baseline catalog and return its membership."""
    try:
        catalog = payload["catalog"]
        metadata = catalog["metadata"]
        groups = catalog["groups"]
    except (KeyError, TypeError):
        raise LoaderError(
            "not an OSCAL resolved catalog (missing catalog.groups)"
        ) from None

    rows = BaselineRows(
        baseline={
            "baseline": baseline,
            "title": metadata.get("title", ""),
            "version": metadata.get("version", ""),
            "oscal_version": metadata.get("oscal-version", ""),
            "last_modified": metadata.get("last-modified", ""),
            "catalog_uuid": catalog.get("uuid", ""),
            "source_key": source_key,
            "source_sha256": source_sha256,
        }
    )
    seen: set[str] = set()
    for group in groups:
        for control in _walk(group.get("controls", [])):
            control_id = parse_control_id(control["id"]).canonical
            if control_id in seen:
                continue
            seen.add(control_id)
            rows.members.append(
                {
                    "baseline": baseline,
                    "control_id": control_id,
                    "oscal_id": control["id"],
                    "title": control.get("title", "").strip(),
                    "position": len(rows.members),
                }
            )
    return rows


def _walk(controls: list[dict]):
    """Controls and their nested enhancements, in document order."""
    for control in controls:
        yield control
        yield from _walk(control.get("controls", []))
