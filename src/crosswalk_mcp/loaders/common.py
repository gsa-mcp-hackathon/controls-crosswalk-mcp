"""Small helpers shared by the loaders."""

from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def html_to_text(value: str) -> str:
    """Flatten the HTML that CPRT uses for discussion text.

    CPRT wraps discussion in <p> tags, sometimes with Word styling pasted in.
    Paragraph breaks become blank lines, every other tag is dropped, and
    entities are decoded. The result is plain text suitable for an LLM.
    """
    if not value:
        return ""
    text = re.sub(r"(?i)</p\s*>", "\n\n", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def natural_key(label: str) -> tuple:
    """Sort key so that a, b, c and 1, 2, 10 both order the way people expect."""
    parts = re.split(r"(\d+)", label)
    return tuple(int(p) if p.isdigit() else p.lower() for p in parts)
