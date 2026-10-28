"""Identifier parsing and normalization across the frameworks we serve.

The same control shows up in four spellings depending on the source:

- NIST publications and our canonical form: ``AC-2(3)``
- CPRT exports: ``AC-02(03)`` (zero padded)
- OSCAL catalogs and FedRAMP rules: ``ac-2.3`` (lowercase, dot separated)
- Loose user input: ``ac 2 (3)``, ``AC-2 (3)``, ``ac-02.03``

CSF 2.0 identifiers look like ``PR.AA-01``, SP 800-171 r3 requirements look
like ``03.01.01``, and FedRAMP Key Security Indicators look like
``KSI-CNA-01``. Everything in this module is pure string handling with no
I/O, so it is safe to call from any tool and cheap to test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class InvalidIdentifier(ValueError):
    """Raised when a string cannot be read as any supported identifier."""


class IdKind(str, Enum):
    """Which framework an identifier belongs to."""

    CONTROL = "control"  # SP 800-53 control or enhancement
    CSF = "csf"  # CSF 2.0 function, category, or subcategory
    REQUIREMENT_171 = "sp800_171"  # SP 800-171 r3 requirement
    KSI = "ksi"  # FedRAMP Key Security Indicator or theme


# Two letter family, number, optional enhancement in parens or after a dot.
# Leading zeros and surrounding whitespace are tolerated everywhere.
_CONTROL_RE = re.compile(
    r"^\s*([A-Za-z]{2})\s*-?\s*0*(\d+)\s*(?:[(.]\s*0*(\d+)\s*\)?)?\s*$"
)

# Function (GV), category (GV.OC), or subcategory (GV.OC-01).
_CSF_RE = re.compile(r"^\s*([A-Za-z]{2})\.([A-Za-z]{2})(?:-0*(\d+))?\s*$")
_CSF_FUNCTION_RE = re.compile(r"^\s*([A-Za-z]{2})\s*$")

# SP 800-171 r3 uses three dotted two digit groups: 03.01.01.
_171_RE = re.compile(r"^\s*0*(\d{1,2})\.0*(\d{1,2})\.0*(\d{1,2})\s*$")

# KSI theme (KSI-CNA) or indicator (KSI-CNA-01, KSI-CED-RAT).
_KSI_RE = re.compile(r"^\s*KSI-([A-Za-z]{3})(?:-([A-Za-z0-9]{1,4}))?\s*$", re.I)


@dataclass(frozen=True, order=True)
class ControlId:
    """A parsed SP 800-53 control or control enhancement identifier."""

    family: str
    number: int
    enhancement: int | None = None

    @property
    def is_enhancement(self) -> bool:
        return self.enhancement is not None

    @property
    def base(self) -> ControlId:
        """The parent control (AC-2 for AC-2(3), AC-2 for AC-2)."""
        return ControlId(self.family, self.number)

    @property
    def canonical(self) -> str:
        """NIST publication style: AC-2 or AC-2(3)."""
        if self.enhancement is None:
            return f"{self.family}-{self.number}"
        return f"{self.family}-{self.number}({self.enhancement})"

    @property
    def cprt(self) -> str:
        """CPRT element style: AC-02 or AC-02(03)."""
        if self.enhancement is None:
            return f"{self.family}-{self.number:02d}"
        return f"{self.family}-{self.number:02d}({self.enhancement:02d})"

    @property
    def oscal(self) -> str:
        """OSCAL and FedRAMP style: ac-2 or ac-2.3."""
        if self.enhancement is None:
            return f"{self.family.lower()}-{self.number}"
        return f"{self.family.lower()}-{self.number}.{self.enhancement}"

    def __str__(self) -> str:
        return self.canonical


def parse_control_id(raw: str) -> ControlId:
    """Parse any supported spelling of an 800-53 control identifier.

    Raises:
        InvalidIdentifier: if the string is not a control identifier.
    """
    match = _CONTROL_RE.match(raw or "")
    if not match:
        raise InvalidIdentifier(f"Not an SP 800-53 control identifier: {raw!r}")
    family, number, enhancement = match.groups()
    return ControlId(
        family=family.upper(),
        number=int(number),
        enhancement=int(enhancement) if enhancement is not None else None,
    )


def normalize_control_id(raw: str) -> str:
    """Return the canonical form (AC-2(3)) of any supported spelling."""
    return parse_control_id(raw).canonical


def to_cprt(raw: str) -> str:
    return parse_control_id(raw).cprt


def to_oscal(raw: str) -> str:
    return parse_control_id(raw).oscal


def normalize_csf_id(raw: str) -> str:
    """Return CSF 2.0 style: GV, GV.OC, or GV.OC-01 (two digit suffix).

    CSF 1.1 identifiers such as DE.DP-5 normalize to DE.DP-05. Whether an
    identifier is active in CSF 2.0 is a data question answered by the store,
    not by this function.
    """
    match = _CSF_RE.match(raw or "")
    if match:
        function, category, number = match.groups()
        head = f"{function.upper()}.{category.upper()}"
        return head if number is None else f"{head}-{int(number):02d}"
    match = _CSF_FUNCTION_RE.match(raw or "")
    if match:
        return match.group(1).upper()
    raise InvalidIdentifier(f"Not a CSF identifier: {raw!r}")


def normalize_171_id(raw: str) -> str:
    """Return SP 800-171 r3 style: 03.01.01."""
    match = _171_RE.match(raw or "")
    if not match:
        raise InvalidIdentifier(f"Not an SP 800-171 requirement identifier: {raw!r}")
    return ".".join(f"{int(part):02d}" for part in match.groups())


def normalize_ksi_id(raw: str) -> str:
    """Return FedRAMP style: KSI-CNA or KSI-CNA-01, upper case."""
    match = _KSI_RE.match(raw or "")
    if not match:
        raise InvalidIdentifier(f"Not a FedRAMP KSI identifier: {raw!r}")
    theme, indicator = match.groups()
    head = f"KSI-{theme.upper()}"
    return head if indicator is None else f"{head}-{indicator.upper()}"


def classify(raw: str) -> IdKind:
    """Guess which framework an identifier belongs to.

    A bare two letter code (``AC``) is ambiguous between an 800-53 family and
    a CSF function, so it is rejected. Callers that know the framework should
    call the specific normalizer instead.

    Raises:
        InvalidIdentifier: if nothing matches.
    """
    text = raw or ""
    if _KSI_RE.match(text):
        return IdKind.KSI
    if _171_RE.match(text):
        return IdKind.REQUIREMENT_171
    if _CSF_RE.match(text):
        return IdKind.CSF
    if _CONTROL_RE.match(text):
        return IdKind.CONTROL
    raise InvalidIdentifier(f"Unrecognized identifier: {raw!r}")


def normalize_id(raw: str) -> tuple[IdKind, str]:
    """Classify and normalize in one step."""
    kind = classify(raw)
    if kind is IdKind.KSI:
        return kind, normalize_ksi_id(raw)
    if kind is IdKind.REQUIREMENT_171:
        return kind, normalize_171_id(raw)
    if kind is IdKind.CSF:
        return kind, normalize_csf_id(raw)
    return kind, normalize_control_id(raw)
