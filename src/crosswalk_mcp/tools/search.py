"""controls_search: find SP 800-53 controls by keyword."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from crosswalk_mcp.models import Baseline, PaginationParams, Release
from crosswalk_mcp.tools.common import (
    get_store,
    release_provenance,
    resolve_family,
    resolve_release,
)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="controls_search",
        annotations={
            "title": "Search SP 800-53 controls",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def controls_search(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description=(
                    "Words to look for in control titles, statements, and "
                    "discussion. All words must match; if nothing matches, the "
                    "search retries with any word and says so. A trailing * "
                    "matches a prefix, for example authent*."
                ),
            ),
        ],
        release: Annotated[
            Release | None,
            Field(description="SP 800-53 release to search. Defaults to 5.2.0."),
        ] = None,
        family: Annotated[
            str | None,
            Field(
                max_length=2,
                description="Limit to one family by its two letters, such as AC.",
            ),
        ] = None,
        baseline: Annotated[
            Baseline | None,
            Field(description="Limit to controls in one SP 800-53B baseline."),
        ] = None,
        include_withdrawn: Annotated[
            bool,
            Field(description="Include withdrawn controls. Off by default."),
        ] = False,
        pagination: PaginationParams | None = None,
    ) -> dict:
        """Search SP 800-53 control text and return the best matches.

        Each hit gives the control id, title, family, a snippet with the
        matched words in square brackets, and a relevance score. Use
        controls_get_control to read a hit in full. To look up a known id,
        call controls_get_control directly instead of searching.
        """
        store = get_store()
        release_key = resolve_release(release)
        family_key = resolve_family(store, family, release_key)
        page = pagination or PaginationParams()
        baseline_key = baseline.value if baseline else None

        match_mode = "all_words"
        with store.lock:
            try:
                total, hits = store.search(
                    query,
                    release_key,
                    family=family_key,
                    baseline=baseline_key,
                    include_withdrawn=include_withdrawn,
                    limit=page.limit,
                    offset=page.offset,
                )
                if total == 0 and len(query.split()) > 1:
                    match_mode = "any_word"
                    total, hits = store.search(
                        query,
                        release_key,
                        family=family_key,
                        baseline=baseline_key,
                        include_withdrawn=include_withdrawn,
                        limit=page.limit,
                        offset=page.offset,
                        any_word=True,
                    )
            except ValueError:
                raise ToolError(
                    "The query has no searchable words. Give one or more plain "
                    "words, for example 'account disable inactive'."
                ) from None
            membership = store.membership([hit["id"] for hit in hits])

        for hit in hits:
            hit["baselines"] = membership[hit["id"]]
        next_offset = page.offset + len(hits)
        notes = []
        if match_mode == "any_word":
            notes.append(
                "No control matched every word, so these results match at "
                "least one word. NIST text often hyphenates terms, for example "
                "multi-factor; try the hyphenated or split spelling."
            )
        return {
            "query": query,
            "match_mode": match_mode,
            "filters": {
                "family": family_key,
                "baseline": baseline_key,
                "include_withdrawn": include_withdrawn,
            },
            "total": total,
            "count": len(hits),
            "offset": page.offset,
            "has_more": next_offset < total,
            "next_offset": next_offset if next_offset < total else None,
            "results": hits,
            "notes": notes,
            "provenance": release_provenance(store, release_key),
        }
