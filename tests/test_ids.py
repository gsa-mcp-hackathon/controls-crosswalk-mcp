"""Identifier normalization must round trip across every spelling we accept."""

from __future__ import annotations

import pytest

from crosswalk_mcp.ids import (
    ControlId,
    IdKind,
    InvalidIdentifier,
    classify,
    normalize_171_id,
    normalize_control_id,
    normalize_csf_id,
    normalize_id,
    normalize_ksi_id,
    parse_control_id,
    to_cprt,
    to_oscal,
)


@pytest.mark.parametrize(
    "raw",
    ["AC-2(3)", "AC-02(03)", "ac-2.3", "ac-02.03", " AC-2 (3) ", "ac 2(3)", "Ac-2.03"],
)
def test_enhancement_spellings_normalize_to_canonical(raw):
    assert normalize_control_id(raw) == "AC-2(3)"


@pytest.mark.parametrize("raw", ["AC-2", "AC-02", "ac-2", "ac-02", " ac 2 "])
def test_base_control_spellings_normalize_to_canonical(raw):
    assert normalize_control_id(raw) == "AC-2"


def test_parse_fields():
    parsed = parse_control_id("SI-07(12)")
    assert parsed == ControlId("SI", 7, 12)
    assert parsed.is_enhancement
    assert parsed.base == ControlId("SI", 7)
    assert not parsed.base.is_enhancement


def test_three_output_styles():
    assert to_cprt("si-7.12") == "SI-07(12)"
    assert to_oscal("SI-07(12)") == "si-7.12"
    assert parse_control_id("SI-07(12)").canonical == "SI-7(12)"


def test_two_digit_numbers_keep_their_digits():
    assert normalize_control_id("AC-20(1)") == "AC-20(1)"
    assert to_cprt("ac-20.1") == "AC-20(01)"
    assert to_oscal("SA-15(13)") == "sa-15.13"


def test_round_trip_through_every_style():
    for raw in ("PM-1", "SR-11(2)", "PT-3(1)", "SA-24"):
        parsed = parse_control_id(raw)
        for spelling in (parsed.canonical, parsed.cprt, parsed.oscal):
            assert parse_control_id(spelling) == parsed


@pytest.mark.parametrize("raw", ["", "AC", "AC-", "A-2", "ABC-2", "AC-2(3)(4)", "2.3"])
def test_rejects_non_control_strings(raw):
    with pytest.raises(InvalidIdentifier):
        parse_control_id(raw)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("PR.AA-01", "PR.AA-01"),
        ("pr.aa-1", "PR.AA-01"),
        ("DE.DP-5", "DE.DP-05"),
        ("GV.OC", "GV.OC"),
        ("gv", "GV"),
    ],
)
def test_csf_normalization(raw, expected):
    assert normalize_csf_id(raw) == expected


def test_csf_rejects_control_style():
    with pytest.raises(InvalidIdentifier):
        normalize_csf_id("AC-2")


@pytest.mark.parametrize(
    "raw, expected",
    [("03.01.01", "03.01.01"), ("3.1.1", "03.01.01"), ("03.1.10", "03.01.10")],
)
def test_171_normalization(raw, expected):
    assert normalize_171_id(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ksi-cna-01", "KSI-CNA-01"),
        ("KSI-CED-RAT", "KSI-CED-RAT"),
        ("ksi-mla", "KSI-MLA"),
    ],
)
def test_ksi_normalization(raw, expected):
    assert normalize_ksi_id(raw) == expected


@pytest.mark.parametrize(
    "raw, kind, expected",
    [
        ("ac-2.3", IdKind.CONTROL, "AC-2(3)"),
        ("pr.aa-1", IdKind.CSF, "PR.AA-01"),
        ("3.1.1", IdKind.REQUIREMENT_171, "03.01.01"),
        ("ksi-cna-01", IdKind.KSI, "KSI-CNA-01"),
    ],
)
def test_classify_and_normalize(raw, kind, expected):
    assert classify(raw) is kind
    assert normalize_id(raw) == (kind, expected)


def test_bare_two_letters_is_ambiguous():
    with pytest.raises(InvalidIdentifier):
        classify("AC")
