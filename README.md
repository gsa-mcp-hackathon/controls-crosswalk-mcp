# Controls Crosswalk MCP

A read-only Model Context Protocol server over NIST SP 800-53, the SP 800-53B baselines, the Cybersecurity Framework (CSF) 2.0, and the FedRAMP Key Security Indicators (KSIs). It helps security teams explain what changed between SP 800-53 releases, trace the relationships these frameworks publish between each other, and retrieve assessment guidance, with every answer tied to its source file, release, and citation.

Built for the 2026 GSA MCP Server Hackathon.

Unofficial: not affiliated with or endorsed by NIST, GSA, or FedRAMP.

## What it answers

- What changed in SI-7(12) between SP 800-53 release 5.1.1 and 5.2.0, and which baselines does that affect?
- Which controls, parameters, objectives, and assessment methods does AC-2 have in the current release?
- Which SP 800-53 families does CSF subcategory PR.AA-01 reference, and which FedRAMP KSIs relate to those controls?
- Which controls does FedRAMP list under KSI-CED-RAT, and what does FedRAMP say about AC-20?
- Is IR-4(4) in the moderate baseline?

Every result carries a `provenance` block with the snapshot hash, the source file and its SHA-256, and a citation URL. Relationship results are labeled `direct` when they are a single published link and `derived` when the server composed links. The server never states that a requirement, control, or indicator is satisfied.

## Data sources

All data is public. GitHub sources are pinned to a commit. CPRT exports cannot be pinned, so the snapshot manifest records the hash of what was fetched and the build refuses to run if the files do not match it.

| Dataset | Publisher | Source | Notes |
|---|---|---|---|
| SP 800-53 Rev. 5, releases 5.1.1 and 5.2.0, with SP 800-53A assessment procedures | NIST | [CPRT](https://csrc.nist.gov/projects/cprt) JSON export | Both full catalogs are stored, so any control can be read in either release |
| SP 800-53B baselines (low, moderate, high, privacy) | NIST | [usnistgov/oscal-content](https://github.com/usnistgov/oscal-content), resolved profile catalogs | Pinned commit |
| CSF 2.0 core with informative references | NIST | CPRT JSON export | This export gives its references to SP 800-53 at the family level, and they target release 5.1.1 |
| FedRAMP Consolidated Rules (KSIs, definitions, control guidance) | FedRAMP | [FedRAMP/rules](https://github.com/FedRAMP/rules) | Pinned commit. Control links are published without naming an SP 800-53 release |

The exact URLs live in `src/crosswalk_mcp/sources.py`. The manifest of fetched files is committed at `data/raw/manifest.json`; the files themselves and the built SQLite store are not.

## Tools

All tools are read-only, take typed parameters, and return structured data.

| Tool | What it does |
|---|---|
| `controls_get_control` | One control or enhancement in full: statement tree, discussion, parameters, assessment objectives and methods, references, related controls, enhancements, baseline flags, withdrawal details, and the FedRAMP KSIs and guidance that name it. Any release. |
| `controls_search` | Full-text search over titles, statements, and discussion, with family, baseline, and release filters. |
| `controls_get_baseline` | The members of one SP 800-53B baseline, optionally one family, paginated. |
| `controls_baseline_membership` | Which baselines select each of up to 50 controls. |
| `controls_diff_releases` | What changed between two releases for the whole catalog, one family, or one control. Control view shows before and after text for statements, parameters, objectives, assessment methods, references, and relations. |
| `controls_get_csf_element` | One CSF 2.0 function, category, or subcategory with examples and its published SP 800-53 family references. Retired CSF 1.1 identifiers are returned as legacy. |
| `controls_get_ksi` | FedRAMP KSI themes, one theme's indicators, or one indicator with its statement, defined terms, change history, and related controls. |
| `controls_crosswalk` | Follow published links from a control, CSF element, or KSI into another framework. Direct and derived hits are reported separately, each with its path, link labels, and citation. |
| `controls_data_status` | Which datasets and releases the server holds, the snapshot hash, and every source URL with its file hash. |

Identifiers are accepted in any common spelling: `AC-2(3)`, `AC-02(03)`, `ac-2.3`, `PR.AA-01`, `pr.aa-1`, `KSI-CNA-EIS`.

## Prompts and resources

Prompts are preset starters that chain the tools and tell the model to stay within what the tools return.

- `review_release_changes` reviews a catalog, family, or control between two releases, with baseline impact and citations.
- `trace_relationships` looks up one identifier and follows its published links into the other frameworks.

Resources are reference lists a client can read without a tool call.

- `crosswalk://data-status` datasets, releases, snapshot hash, and sources.
- `crosswalk://families` SP 800-53 family ids and titles per release.
- `crosswalk://csf-outline` CSF 2.0 functions and categories.
- `crosswalk://ksi-themes` FedRAMP KSI themes and their indicators.

## Setup

You need [uv](https://docs.astral.sh/uv/). Python 3.11 is installed by uv.

```bash
cp .env.example .env
uv sync --group dev
```

The server reads a SQLite store that is built once from the fetched source files. Building is an operator step, never done at request time.

```bash
# 1. Download the sources and write data/raw/manifest.json (about 45 MB).
uv run python -m crosswalk_mcp.snapshot fetch

# 2. Build data/crosswalk.sqlite from them (a few seconds).
uv run python -m crosswalk_mcp.store build

# 3. Confirm what was built.
uv run python -m crosswalk_mcp.store status
```

If a downloaded file differs from the committed manifest, NIST or FedRAMP republished it. `fetch` says so, writes the new manifest, and the server works on the new snapshot; the difference is visible in every result's provenance and in the manifest diff. A file already on disk is different: if it no longer matches the manifest, `fetch` stops and does not write a new manifest. Download that file again with `fetch --force --only <source>`. To check the files you have against the manifest, run `uv run python -m crosswalk_mcp.snapshot verify`.

On a laptop with TLS interception, set `SSL_CERT_FILE` to your CA bundle before running `fetch`. The fetch honors proxy and certificate environment variables; the server itself never makes network calls.

## Run

Local clients launch the server over stdio. Add this to Claude Code's `.mcp.json` or Claude Desktop's config, with the absolute path to this repo:

```json
{
  "mcpServers": {
    "controls-crosswalk": {
      "command": "uv",
      "args": ["run", "crosswalk-mcp"],
      "cwd": "/absolute/path/to/controls-crosswalk-mcp"
    }
  }
}
```

Then try: "What changed in SI-7(12) between SP 800-53 5.1.1 and 5.2.0?" or use the `trace_relationships` prompt with `PR.AA-01`.

To serve HTTP instead, for a container or an agent platform:

```bash
MCP_TRANSPORT=streamable-http uv run python main.py
curl http://localhost:8000/health
```

The MCP endpoint is `/mcp`. `/health` returns 503 until the store has been built, because no data tool can answer without it. The server also switches to HTTP on its own when a platform sets `PORT` or `DATABRICKS_APP_PORT`. See [deploy/README.md](deploy/README.md) for the IBM watsonx Orchestrate and Databricks kits from the template.

## Verify

```bash
uv run pytest -q                    # offline, against a tiny fixture store
uv run ruff check src tests
uv run ruff format --check src tests
```

Tests marked with the real store run only when `data/crosswalk.sqlite` exists. They check facts verified by hand against the published files: the 106 active CSF 2.0 subcategories, the three controls added in 5.2.0, the 46 KSIs, and more. CI runs the same lint, format check, and tests on every push.

## How it is built

```
src/crosswalk_mcp/
├── app.py            FastMCP instance, transport selection
├── config.py         settings read from environment variables
├── routes.py         HTTP-only routes: health and version
├── sources.py        the pinned public sources
├── snapshot.py       fetch sources, write and verify the manifest
├── loaders/          one pure function per source file, returning rows
├── store.py          SQLite schema, build step, read methods
├── diff.py           release comparison, section by section
├── ids.py            identifier parsing and normalization
├── models.py         enums and Pydantic parameter models
├── tools/            one file per tool, plus common.py for provenance
├── prompts/          one file per prompt
└── resources/        reference lists
```

Loaders never touch the network or the database. The store is opened read-only, and one connection serves all tools under a lock. Full-text search uses SQLite FTS5 with every query word quoted, so operators in user input cannot change the query. Text is reproduced from the sources without change; the server adds labels and citations, never judgments.

## Scope and limits

- The CSF to SP 800-53 mapping in NIST's CPRT export names families, not controls. The server returns it that way and says so. NIST publishes control-level mappings in a separate [informative reference catalog](https://www.nist.gov/cyberframework/csf-20-informative-references), which this server does not hold. Control-level crosswalks from CSF are always labeled derived.
- A `controls_get_control` result that includes FedRAMP content names the FedRAMP file in `provenance.fedramp`, beside the NIST source.
- FedRAMP's related control lists name no SP 800-53 release. The server resolves titles and baselines against 5.2.0 and labels the release as unspecified.
- Derived paths chain at most two published links through family membership. They are a starting point for analysis, not a published mapping.
- No writes, no OSCAL generation, no vulnerability data, no compliance verdicts, no authentication on the pilot endpoint, no AI RMF.
- The `Dockerfile` from the template installs the server but not the data. Build the store and mount or copy it to the image's data directory before use. The tested path for this submission is the local stdio server.

## Evaluation

The results are in [eval/EVALUATION.md](eval/EVALUATION.md), and the raw runs behind them are in [eval/results/2026-11-20](eval/results/2026-11-20/README.md). Two layers, described in [eval/README.md](eval/README.md):

- `uv run eval/gold_check.py` re-derives the fifteen gold answers through the tools with no model and reports any that moved. It also runs under pytest when the real store exists.
- `eval/phoenix/` runs a LangChain agent against the server over stdio and scores each answer with a correctness judge and a scope judge, with traces in Arize Phoenix. A no-tool baseline and repeated runs show what the server adds and how consistent the answers are. It needs the `eval` dependency group and a model key for IBM watsonx.ai or OpenAI; see [eval/phoenix/README.md](eval/phoenix/README.md).

## Deployment

See [deploy/README.md](deploy/README.md) for the template's IBM watsonx Orchestrate and Databricks kits. Packaging the built store with the server for those kits is the next piece of work.

## License

[MIT](LICENSE). See [SECURITY.md](SECURITY.md) for the vulnerability disclosure policy. Source content belongs to its publishers; NIST publications are in the public domain, and the FedRAMP rules file states no license, so the fetched files are not vendored in this repository.
