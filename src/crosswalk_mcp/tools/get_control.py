"""controls_get_control: one SP 800-53 control or enhancement, in full."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from crosswalk_mcp.models import Release, Section
from crosswalk_mcp.store import FEDRAMP_SOURCE, Store
from crosswalk_mcp.tools.common import (
    cprt_citation,
    get_store,
    release_provenance,
    resolve_control_id,
    resolve_release,
    source_record,
)

# Which result keys each optional section controls. Everything else in the
# record (id, title, family, withdrawn, baselines) is always returned.
SECTION_KEYS: dict[Section, tuple[str, ...]] = {
    Section.STATEMENT: ("statement", "statement_text"),
    Section.DISCUSSION: ("discussion",),
    Section.PARAMETERS: ("parameters",),
    Section.OBJECTIVES: ("objectives",),
    Section.ASSESSMENT_METHODS: ("assessment_methods",),
    Section.REFERENCES: ("references",),
    Section.RELATIONS: ("related", "incorporated_into", "moved_to"),
    Section.ENHANCEMENTS: ("enhancements",),
    Section.FEDRAMP: ("fedramp_ksis", "fedramp_guidance"),
}


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="controls_get_control",
        annotations={
            "title": "Get an SP 800-53 control",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def controls_get_control(
        control_id: Annotated[
            str,
            Field(
                description=(
                    "Control or enhancement id in any common spelling: "
                    "AC-2, AC-2(3), AC-02(03), or ac-2.3."
                )
            ),
        ],
        release: Annotated[
            Release | None,
            Field(
                description=(
                    "SP 800-53 release to read. Defaults to the newest, 5.2.0. "
                    "Use 5.1.1 to see the text before the 2025 update."
                )
            ),
        ] = None,
        sections: Annotated[
            list[Section] | None,
            Field(
                description=(
                    "Limit the record to these sections to save space. "
                    "Unset returns everything."
                )
            ),
        ] = None,
    ) -> dict:
        """Return the published text and structure of one SP 800-53 control.

        The record includes the control statement as a tree, the discussion,
        organization-defined parameters, SP 800-53A assessment objectives
        and methods, references, related controls, enhancements, baseline
        flags, and withdrawal details. Text is exactly as NIST publishes it
        in CPRT; this tool never judges whether a requirement is met.

        The fedramp section lists the FedRAMP Key Security Indicators that
        name this control as a related control, and any FedRAMP guidance or
        parameter values for it, as published in the consolidated rules.

        Data is a fixed snapshot. The `provenance` block names the snapshot
        hash, the source file, and a citation URL on csrc.nist.gov. When the
        result holds FedRAMP content, `provenance.fedramp` names the pinned
        FedRAMP file and where each record sits in it.
        """
        store = get_store()
        wanted = resolve_control_id(control_id)
        release_key = resolve_release(release)
        with store.lock:
            record = store.get_control(wanted, release_key)
            if record is None:
                raise ToolError(_not_found_message(store, wanted, release_key))
            # FedRAMP links are published without a catalog release, so they
            # are attached to the control under every release.
            record["fedramp_ksis"] = [
                {"id": row["id"], "name": row["name"], "theme_id": row["theme_id"]}
                for row in store.ksis_for_controls([wanted])
            ]
            record["fedramp_guidance"] = store.fedramp_guidance(wanted)

        if sections:
            keep = {key for section in sections for key in SECTION_KEYS[section]}
            drop = {key for keys in SECTION_KEYS.values() for key in keys} - keep
            for key in drop:
                record.pop(key, None)

        notes = []
        if record["withdrawn"]:
            notes.append(
                f"{wanted} is withdrawn in release {release_key}: "
                f"{record['withdraw_reason']}."
            )
        provenance = {
            **release_provenance(store, release_key),
            "citation": cprt_citation(
                store, release_key, record["cprt_id"], record["title"]
            ),
        }
        with store.lock:
            fedramp = _fedramp_provenance(store, wanted, record)
        if fedramp:
            provenance["fedramp"] = fedramp
        return {"control": record, "notes": notes, "provenance": provenance}


def _fedramp_provenance(store: Store, control_id: str, record: dict) -> dict | None:
    """Where the FedRAMP parts of a control record came from.

    The KSI links and the guidance are published by FedRAMP, not NIST, so a
    reader needs the FedRAMP file to check them. Returns None when the
    record holds no FedRAMP content.
    https://github.com/FedRAMP/rules
    """
    ksis = record.get("fedramp_ksis") or []
    guidance = record.get("fedramp_guidance") or []
    if not ksis and not guidance:
        return None
    document = store.fedramp_document()
    source = source_record(store, FEDRAMP_SOURCE)
    paths = [
        f"KSI.{k['theme_id'].removeprefix('KSI-')}.indicators.{k['id']}" for k in ksis
    ]
    if guidance:
        paths.append(f"CTL.{record['family']}.{_ctl_key(control_id)}")
    return {
        "source": source,
        "document": {
            "title": document["title"],
            "version": document["version"],
            "last_updated": document["last_updated"],
        },
        "citation": {
            "text": (
                f"{document['title']}, version {document['version']}, "
                f"records that name {control_id}"
            ),
            "url": source["url"],
            "json_paths": paths,
        },
    }


def _ctl_key(control_id: str) -> str:
    """AC-6(1) to AC-06-01, the way the FedRAMP file keys its CTL section."""
    family, _, rest = control_id.partition("-")
    number, _, enhancement = rest.partition("(")
    key = f"{family}-{int(number):02d}"
    if enhancement:
        key += f"-{int(enhancement.rstrip(')')):02d}"
    return key


def _not_found_message(store, control_id: str, release: str) -> str:
    """Say where else the id exists, so the caller can retry sensibly."""
    elsewhere = [
        r["release"]
        for r in store.releases()
        if r["release"] != release and store.get_control(control_id, r["release"])
    ]
    if elsewhere:
        return (
            f"{control_id} is not in SP 800-53 release {release}, but it is in "
            f"release {', '.join(elsewhere)}. Call again with release set to one "
            "of those."
        )
    return (
        f"{control_id} is not in SP 800-53 release {release} or any other release "
        "this server holds. Check the family letters and number, or use "
        "controls_search to find the control by keyword."
    )
