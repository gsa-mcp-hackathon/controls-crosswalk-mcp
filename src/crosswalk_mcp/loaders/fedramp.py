"""Load the FedRAMP consolidated rules file into store rows.

FedRAMP publishes its rules as one JSON file with four sections:

    FRD  definitions of terms the rules use
    FRR  the rules themselves (not loaded; this server is about controls)
    KSI  Key Security Indicators, grouped in themes, each listing the
         SP 800-53 controls FedRAMP calls "Related SP 800-53 Controls"
    CTL  control specific guidance and parameter values

Five indicators vary by authorization class (b, c, d) and carry one
statement per class instead of a single statement. The loader keeps both
forms. Control ids in the file use the OSCAL spelling (at-2.2); rows store
the canonical spelling (AT-2(2)) next to it. The file does not say which
SP 800-53 release its control ids refer to, so the store records none.
https://github.com/FedRAMP/rules
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from crosswalk_mcp.ids import InvalidIdentifier, parse_control_id
from crosswalk_mcp.loaders.sp800_53 import LoaderError


@dataclass
class FedrampRows:
    """Rows for every fedramp_* table, keyed by the table's short name."""

    document: dict
    themes: list[dict] = field(default_factory=list)
    indicators: list[dict] = field(default_factory=list)
    indicator_classes: list[dict] = field(default_factory=list)
    indicator_controls: list[dict] = field(default_factory=list)
    definitions: list[dict] = field(default_factory=list)
    control_guidance: list[dict] = field(default_factory=list)


def load(payload: dict, source_key: str, source_sha256: str) -> FedrampRows:
    """Parse the consolidated rules file and return rows for the store."""
    try:
        info = payload["info"]
        themes = payload["KSI"]
        definitions = payload["FRD"]["data"]
        guidance = payload["CTL"]
    except (KeyError, TypeError):
        raise LoaderError(
            "not a FedRAMP consolidated rules file (missing info, KSI, FRD, or CTL)"
        ) from None

    rows = FedrampRows(
        document={
            "title": info["title"],
            "version": info["version"],
            "last_updated": info["last_updated"],
            "source_key": source_key,
            "source_sha256": source_sha256,
        }
    )

    for theme_position, theme in enumerate(themes.values()):
        rows.themes.append(
            {
                "id": theme["id"],
                "short_name": theme["short_name"],
                "name": theme["name"],
                "web_name": theme["web_name"],
                "status": theme["status"],
                "position": theme_position,
            }
        )
        for position, (indicator_id, indicator) in enumerate(
            theme["indicators"].items()
        ):
            rows.indicators.append(
                {
                    "id": indicator_id,
                    "theme_id": theme["id"],
                    "name": indicator["name"],
                    "statement": indicator.get("statement"),
                    "position": position,
                    "updated": json.dumps(indicator.get("updated", [])),
                    "terms": json.dumps(indicator.get("terms", [])),
                }
            )
            for class_name, variant in indicator.get("varies_by_class", {}).items():
                rows.indicator_classes.append(
                    {
                        "indicator_id": indicator_id,
                        "class": class_name,
                        "statement": variant["statement"],
                    }
                )
            for control_position, oscal_id in enumerate(indicator["controls"]):
                rows.indicator_controls.append(
                    {
                        "indicator_id": indicator_id,
                        "control_id": _control_id(oscal_id, indicator_id),
                        "oscal_id": oscal_id,
                        "position": control_position,
                    }
                )

    for group in definitions.values():
        for definition_id, definition in group.items():
            rows.definitions.append(
                {
                    "id": definition_id,
                    "term": definition["term"],
                    "definition": definition["definition"],
                    "note": definition.get("note"),
                    "tag": definition.get("tag"),
                    "alts": json.dumps(definition.get("alts", [])),
                }
            )

    # CTL keys spell controls as AC-06-01. Guidance and parameters either
    # apply to every class or sit under varies_by_class; one row per class.
    for family in guidance.values():
        for ctl_id, entry in family.items():
            control_id = _control_id(_ctl_to_oscal(ctl_id), ctl_id)
            variants = entry.get("varies_by_class") or {None: entry}
            for class_name, variant in variants.items():
                rows.control_guidance.append(
                    {
                        "control_id": control_id,
                        "class": class_name,
                        "guidance": json.dumps(variant.get("guidance", [])),
                        "parameters": json.dumps(variant.get("parameters", [])),
                        "updated": json.dumps(entry.get("updated", [])),
                    }
                )
    return rows


def _ctl_to_oscal(ctl_id: str) -> str:
    """AC-06-01 (a CTL key) to ac-6.1, which the id parser reads."""
    family, number, *enhancement = ctl_id.split("-")
    base = f"{family}-{number}"
    return f"{base}.{enhancement[0]}" if enhancement else base


def _control_id(raw: str, owner: str) -> str:
    try:
        return parse_control_id(raw).canonical
    except InvalidIdentifier:
        raise LoaderError(f"{owner}: unreadable control id {raw!r}") from None
