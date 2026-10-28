"""Pydantic models and enums for tool parameters.

Typed parameters give MCP clients a precise schema, which helps the model
call the tools correctly. Closed sets of values are enums.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Release(str, Enum):
    """SP 800-53 releases the store holds. The newest is the default."""

    R5_2_0 = "5.2.0"
    R5_1_1 = "5.1.1"


LATEST_RELEASE = Release.R5_2_0


class Section(str, Enum):
    """Optional parts of a control record. Leave unset to get all of them."""

    STATEMENT = "statement"
    DISCUSSION = "discussion"
    PARAMETERS = "parameters"
    OBJECTIVES = "objectives"
    ASSESSMENT_METHODS = "assessment_methods"
    REFERENCES = "references"
    RELATIONS = "relations"
    ENHANCEMENTS = "enhancements"


class PaginationParams(BaseModel):
    """Reusable pagination inputs for list style tools."""

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of items to return (1 to 100).",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of items to skip from the start of the result set.",
    )
