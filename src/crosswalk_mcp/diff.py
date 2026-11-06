"""Compare one control, or a whole catalog, between two SP 800-53 releases.

These are pure functions over the control records the store returns, so
they are easy to test and the same code serves the single control view and
the catalog summary. Text comparison uses difflib from the standard
library. https://docs.python.org/3/library/difflib.html
"""

from __future__ import annotations

import difflib
import re

# Result keys in the order they appear in `changed_sections`.
SECTIONS = (
    "title",
    "statement",
    "discussion",
    "parameters",
    "objectives",
    "assessment_methods",
    "references",
    "relations",
    "withdrawal",
)

RELATION_KINDS = ("related", "incorporated_into", "moved_to")
PARAMETER_FIELDS = ("label", "guideline", "kind", "statement", "choices")
OBJECTIVE_FIELDS = ("statement_id", "text", "parameter_ids")

# How many words of unchanged text to keep on each side of a change.
CONTEXT_WORDS = 6

# Tokens are words and paragraph breaks. A single newline is whitespace.
_TOKEN_RE = re.compile(r"\n\s*\n|\S+")


def text_changes(before: str, after: str, context: int = CONTEXT_WORDS) -> list[dict]:
    """Word level changes between two texts, each with a little context.

    Returns one record per changed region with the old and new wording.
    Whitespace differences alone do not count as a change.
    """
    old_words = _tokens(before)
    new_words = _tokens(after)
    matcher = difflib.SequenceMatcher(a=old_words, b=new_words, autojunk=False)
    hunks = []
    for group in matcher.get_grouped_opcodes(context):
        a_start, a_end = group[0][1], group[-1][2]
        b_start, b_end = group[0][3], group[-1][4]
        hunks.append(
            {
                "before": _join(old_words[a_start:a_end]),
                "after": _join(new_words[b_start:b_end]),
            }
        )
    return hunks


def _tokens(text: str) -> list[str]:
    return ["\n\n" if t.startswith("\n") else t for t in _TOKEN_RE.findall(text)]


def _join(words: list[str]) -> str:
    text = " ".join(words)
    return re.sub(r" ?\n\n ?", "\n\n", text).strip()


def _same_text(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def _flatten_statement(nodes: list[dict], parent: str | None = None) -> dict:
    flat = {}
    for node in nodes:
        flat[node["id"]] = {
            "id": node["id"],
            "label": node["label"],
            "text": node["text"],
            "parent_id": parent,
        }
        flat.update(_flatten_statement(node.get("items", []), node["id"]))
    return flat


def _diff_keyed(before: dict, after: dict, fields: tuple[str, ...]) -> dict | None:
    """Added, removed, and changed entries of two dicts keyed by id."""
    added = [after[k] for k in after if k not in before]
    removed = [before[k] for k in before if k not in after]
    changed = []
    for key in before:
        if key not in after:
            continue
        fields_changed = {}
        for field in fields:
            old, new = before[key].get(field), after[key].get(field)
            if isinstance(old, str) and isinstance(new, str):
                if _same_text(old, new):
                    continue
            elif old == new:
                continue
            fields_changed[field] = {"before": old, "after": new}
        if fields_changed:
            changed.append({"id": key, "fields": fields_changed})
    if not (added or removed or changed):
        return None
    return {"added": added, "removed": removed, "changed": changed}


def _diff_sets(before: list, after: list) -> dict | None:
    added = [x for x in after if x not in before]
    removed = [x for x in before if x not in after]
    if not (added or removed):
        return None
    return {"added": added, "removed": removed}


def diff_controls(before: dict, after: dict) -> dict:
    """Section by section changes between two records of the same control.

    Both records come from Store.get_control or Store.release_records. The
    result maps a section name to its change record and leaves out sections
    that did not change, so an empty dict means the control is unchanged.
    """
    changes: dict[str, dict] = {}

    if not _same_text(before["title"], after["title"]):
        changes["title"] = {"before": before["title"], "after": after["title"]}

    statement = _diff_keyed(
        _flatten_statement(before["statement"]),
        _flatten_statement(after["statement"]),
        ("label", "text"),
    )
    if statement:
        changes["statement"] = statement

    if not _same_text(before["discussion"], after["discussion"]):
        changes["discussion"] = {
            "changes": text_changes(before["discussion"], after["discussion"])
        }

    parameters = _diff_keyed(
        {p["id"]: p for p in before["parameters"]},
        {p["id"]: p for p in after["parameters"]},
        PARAMETER_FIELDS,
    )
    if parameters:
        changes["parameters"] = parameters

    objectives = _diff_keyed(
        {o["id"]: o for o in before["objectives"]},
        {o["id"]: o for o in after["objectives"]},
        OBJECTIVE_FIELDS,
    )
    if objectives:
        changes["objectives"] = objectives

    methods = {}
    old_methods, new_methods = before["assessment_methods"], after["assessment_methods"]
    for method in sorted(set(old_methods) | set(new_methods)):
        old, new = old_methods.get(method, ""), new_methods.get(method, "")
        if not _same_text(old, new):
            methods[method] = {"changes": text_changes(old, new)}
    if methods:
        changes["assessment_methods"] = methods

    references = _diff_sets(before["references"], after["references"])
    if references:
        changes["references"] = references

    relations = {}
    for kind in RELATION_KINDS:
        delta = _diff_sets(before.get(kind, []), after.get(kind, []))
        if delta:
            relations[kind] = delta
    if relations:
        changes["relations"] = relations

    if before["withdrawn"] != after["withdrawn"] or not _same_text(
        before.get("withdraw_reason") or "", after.get("withdraw_reason") or ""
    ):
        changes["withdrawal"] = {
            "before": {
                "withdrawn": before["withdrawn"],
                "reason": before.get("withdraw_reason"),
            },
            "after": {
                "withdrawn": after["withdrawn"],
                "reason": after.get("withdraw_reason"),
            },
        }

    return {section: changes[section] for section in SECTIONS if section in changes}


def _brief(record: dict) -> dict:
    return {
        "id": record["id"],
        "title": record["title"],
        "parent_id": record.get("parent_id"),
        "withdrawn": record["withdrawn"],
    }


def diff_catalog(before: dict[str, dict], after: dict[str, dict]) -> dict:
    """Compare two releases given their records keyed by control id.

    Returns the added and removed controls, one line per changed control
    naming the sections that changed, and the count of unchanged controls.
    Lists are in catalog order.
    """
    order = sorted(
        set(before) | set(after),
        key=lambda i: (after.get(i) or before[i])["sort_key"],
    )
    added, removed, changed = [], [], []
    unchanged = 0
    for control_id in order:
        if control_id not in before:
            added.append(_brief(after[control_id]))
        elif control_id not in after:
            removed.append(_brief(before[control_id]))
        else:
            delta = diff_controls(before[control_id], after[control_id])
            if delta:
                changed.append(
                    {**_brief(after[control_id]), "changed_sections": list(delta)}
                )
            else:
                unchanged += 1
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
    }
