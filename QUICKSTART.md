# Quickstart: run the Controls Crosswalk MCP in 5 minutes

New to MCP? This gets you from clone to a running server connected to a client.
The [README](README.md) has the full picture.

## 1. Install prerequisites

You need [uv](https://docs.astral.sh/uv/) (a fast Python package manager):

```bash
pip install uv     # or: brew install uv
```

## 2. Set up the project

```bash
cp .env.example .env
uv sync --group dev
```

Then fetch the public source files and build the SQLite store the server
reads. Both are one-time operator steps:

```bash
uv run python -m crosswalk_mcp.snapshot fetch
uv run python -m crosswalk_mcp.store build
```

## 3. Run the server

```bash
uv run python main.py
```

The server starts in **stdio** mode and waits for a client to connect over
stdin/stdout. That is correct. It does not print a URL, because a local MCP
server is launched by the client as a subprocess. Press `Ctrl-C` to stop it.

## 4. Connect a client

### Claude Code

Create or edit `.mcp.json` (or your user MCP settings) with the **absolute path**
to this repo:

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

### Claude Desktop

Add the same block to
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows), then restart Claude
Desktop.

Once connected, ask something the tools can answer, for example:

> "What changed in SI-7(12) between SP 800-53 5.1.1 and 5.2.0?"

The answer should quote the before and after text and end with a citation URL
on csrc.nist.gov. That proves the wiring and the data store both work.

## 5. Verify everything

```bash
uv sync --group dev
uv run pytest tests/ -v      # tests pass
uv run ruff check .          # lint clean
```

## 6. Test HTTP mode (optional)

Cloud hosts run the server over HTTP. Try it locally:

```bash
MCP_TRANSPORT=streamable-http uv run python main.py
# in another terminal:
curl http://localhost:8000/health      # {"status":"healthy",...}
```

---

## Next steps

- Read the tool list and the scope notes in the [README](README.md).
- Try the `review_release_changes` and `trace_relationships` prompts from
  your client's prompt picker.
- To share the server with an agent platform, pick a kit in
  [deploy/README.md](deploy/README.md).
