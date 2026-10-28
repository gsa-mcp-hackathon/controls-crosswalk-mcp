"""The pinned public data sources this server is built from.

Every source is public government data. GitHub sources are pinned to a commit
SHA so a rebuild fetches the same bytes. CPRT export URLs cannot be pinned
(NIST can republish in place), so the snapshot manifest records the SHA-256
of what was actually fetched and the build verifies against it.

Reference pages:

- CPRT, the NIST Cybersecurity and Privacy Reference Tool:
  https://csrc.nist.gov/projects/cprt
- OSCAL content from NIST, including the resolved 800-53B baselines:
  https://github.com/usnistgov/oscal-content
- FedRAMP machine readable rules, including the Key Security Indicators:
  https://github.com/FedRAMP/rules
"""

from __future__ import annotations

from dataclasses import dataclass

# Commit pins. Update deliberately and record the change in the manifest.
OSCAL_CONTENT_SHA = "f0de6d8d8c059d374f15e0ae07508d82e370fc1d"  # 2026-10-22
FEDRAMP_RULES_SHA = "a89d78477ddea98dc57eca24f5007794c2b4eeb6"  # 2026-10-13

_CPRT_EXPORT = (
    "https://csrc.nist.gov/extensions/nudp/services/json/nudp/framework/version/"
    "{version}/export/json?element=all"
)
_OSCAL_BASELINE = (
    "https://raw.githubusercontent.com/usnistgov/oscal-content/"
    f"{OSCAL_CONTENT_SHA}/nist.gov/SP800-53/rev5/json/"
    "NIST_SP-800-53_rev5_{level}-baseline-resolved-profile_catalog.json"
)
_FEDRAMP_RULES = (
    "https://raw.githubusercontent.com/FedRAMP/rules/"
    f"{FEDRAMP_RULES_SHA}/fedramp-consolidated-rules.json"
)


@dataclass(frozen=True)
class Source:
    """One downloadable file and where it came from."""

    key: str
    url: str
    filename: str
    publisher: str
    description: str
    pin: str = ""  # commit SHA for GitHub sources, empty when unpinnable


SOURCES: tuple[Source, ...] = (
    Source(
        key="sp800_53_5_2_0",
        url=_CPRT_EXPORT.format(version="sp_800_53_5_2_0"),
        filename="cprt_sp800_53_5_2_0.json",
        publisher="NIST",
        description="SP 800-53 release 5.2.0 with 800-53A assessment procedures",
    ),
    Source(
        key="sp800_53_5_1_1",
        url=_CPRT_EXPORT.format(version="sp_800_53_5_1_1"),
        filename="cprt_sp800_53_5_1_1.json",
        publisher="NIST",
        description="SP 800-53 release 5.1.1 with 800-53A assessment procedures",
    ),
    Source(
        key="csf_2_0_0",
        url=_CPRT_EXPORT.format(version="csf_2_0_0"),
        filename="cprt_csf_2_0_0.json",
        publisher="NIST",
        description="CSF 2.0 core with informative references to SP 800-53 5.1.1",
    ),
    *(
        Source(
            key=f"baseline_{level.lower()}",
            url=_OSCAL_BASELINE.format(level=level),
            filename=f"oscal_sp800_53b_{level.lower()}.json",
            publisher="NIST",
            description=f"SP 800-53B {level} baseline, resolved OSCAL catalog",
            pin=OSCAL_CONTENT_SHA,
        )
        for level in ("LOW", "MODERATE", "HIGH", "PRIVACY")
    ),
    Source(
        key="fedramp_rules",
        url=_FEDRAMP_RULES,
        filename="fedramp_consolidated_rules.json",
        publisher="FedRAMP",
        description="FedRAMP consolidated rules including Key Security Indicators",
        pin=FEDRAMP_RULES_SHA,
    ),
)

SOURCES_BY_KEY: dict[str, Source] = {source.key: source for source in SOURCES}
