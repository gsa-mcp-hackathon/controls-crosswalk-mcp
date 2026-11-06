"""Tests for the pure comparison functions in crosswalk_mcp.diff."""

from __future__ import annotations

from crosswalk_mcp.diff import diff_catalog, diff_controls, text_changes


def record(**overrides) -> dict:
    """A minimal control record in the shape Store.get_control returns."""
    base = {
        "id": "AC-2",
        "title": "ACCOUNT MANAGEMENT",
        "parent_id": None,
        "sort_key": "00001.00002",
        "withdrawn": False,
        "withdraw_reason": None,
        "statement": [
            {
                "id": "CST-AC-02",
                "label": None,
                "text": "",
                "items": [
                    {"id": "CST-AC-02-a", "label": "a", "text": "Define;", "items": []},
                ],
            }
        ],
        "discussion": "One two three four five six seven eight nine ten.",
        "parameters": [
            {
                "id": "AC-02_ODP[01]",
                "label": "x",
                "guideline": "x is defined;",
                "kind": "assignment",
                "statement": None,
                "choices": None,
            }
        ],
        "objectives": [
            {
                "id": "DS-AC-02a.",
                "statement_id": "CST-AC-02-a",
                "text": "x is defined;",
                "parameter_ids": ["AC-02_ODP[01]"],
            }
        ],
        "assessment_methods": {"examine": "[SELECT FROM: policy]."},
        "references": [{"title": "SP 800-162", "url": "https://example.invalid/162"}],
        "related": ["AU-6"],
        "incorporated_into": [],
        "moved_to": [],
    }
    base.update(overrides)
    return base


def test_text_changes_reports_words_with_context():
    before = "One two three four five six seven eight nine ten."
    after = "One two three four five SIX seven eight nine ten."
    assert text_changes(before, after, context=2) == [
        {"before": "four five six seven eight", "after": "four five SIX seven eight"}
    ]
    assert text_changes(before, before) == []
    # Whitespace only differences are not changes.
    assert text_changes("a  b\nc", "a b c") == []


def test_text_changes_keeps_paragraph_breaks():
    hunks = text_changes("First.\n\nSecond.", "First.\n\nSecond.\n\nThird.")
    assert hunks == [
        {"before": "First.\n\nSecond.", "after": "First.\n\nSecond.\n\nThird."}
    ]


def test_diff_controls_unchanged_ignores_whitespace():
    assert (
        diff_controls(
            record(),
            record(discussion="One  two three four five six seven eight nine ten."),
        )
        == {}
    )


def test_diff_controls_reports_each_section_in_order():
    before = record()
    after = record(
        title="ACCOUNT MANAGEMENT AND MORE",
        statement=[
            {
                "id": "CST-AC-02",
                "label": None,
                "text": "",
                "items": [
                    {
                        "id": "CST-AC-02-a",
                        "label": "a",
                        "text": "Define all;",
                        "items": [],
                    },
                    {"id": "CST-AC-02-b", "label": "b", "text": "Assign;", "items": []},
                ],
            }
        ],
        discussion="One two three four five six seven eight nine ten eleven.",
        parameters=[],
        objectives=[
            {
                "id": "DS-AC-02a.",
                "statement_id": "CST-AC-02-a",
                "text": "x is defined;",
                "parameter_ids": [],
            }
        ],
        assessment_methods={"examine": "[SELECT FROM: policy; records]."},
        references=[],
        related=["AU-6", "AC-25"],
        withdrawn=True,
        withdraw_reason="Incorporated into AC-25",
    )
    delta = diff_controls(before, after)
    assert list(delta) == [
        "title",
        "statement",
        "discussion",
        "parameters",
        "objectives",
        "assessment_methods",
        "references",
        "relations",
        "withdrawal",
    ]
    assert delta["title"] == {
        "before": "ACCOUNT MANAGEMENT",
        "after": "ACCOUNT MANAGEMENT AND MORE",
    }
    assert delta["statement"]["added"][0]["id"] == "CST-AC-02-b"
    assert delta["statement"]["changed"][0]["fields"]["text"]["after"] == "Define all;"
    assert delta["discussion"]["changes"][0]["after"].endswith("ten eleven.")
    assert delta["parameters"]["removed"][0]["id"] == "AC-02_ODP[01]"
    assert delta["objectives"]["changed"][0]["fields"] == {
        "parameter_ids": {"before": ["AC-02_ODP[01]"], "after": []}
    }
    assert delta["assessment_methods"]["examine"]["changes"][0]["after"].endswith(
        "records]."
    )
    assert delta["references"]["removed"][0]["title"] == "SP 800-162"
    assert delta["relations"] == {"related": {"added": ["AC-25"], "removed": []}}
    assert delta["withdrawal"]["after"] == {
        "withdrawn": True,
        "reason": "Incorporated into AC-25",
    }


def test_diff_catalog_groups_controls_in_catalog_order():
    before = {"AC-2": record(), "AC-3": record(id="AC-3", sort_key="00001.00003")}
    after = {
        "AC-2": record(title="ACCOUNTS"),
        "AC-25": record(id="AC-25", title="REFERENCE MONITOR", sort_key="00001.00025"),
        "AC-1": record(id="AC-1", sort_key="00001.00001"),
    }
    result = diff_catalog(before, after)
    assert [c["id"] for c in result["added"]] == ["AC-1", "AC-25"]
    assert [c["id"] for c in result["removed"]] == ["AC-3"]
    assert result["changed"] == [
        {
            "id": "AC-2",
            "title": "ACCOUNTS",
            "parent_id": None,
            "withdrawn": False,
            "changed_sections": ["title"],
        }
    ]
    assert result["unchanged"] == 0
