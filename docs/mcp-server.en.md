# MCP Server — Cloud Intelligence Platform (CIP)

MCP (Model Context Protocol) server that exposes CIP as a tool for external
agents (Cursor, Kiro, Claude Desktop, etc.).

## Tools

| Tool         | Description                                                                 | Requires API? |
|--------------|-----------------------------------------------------------------------------|---------------|
| `cip_ask`    | Query architecture/best practices for the 3 clouds (pure RAG, with sources).| Yes           |
| `cip_inspect`| Analyze Terraform (.tf) or K8s YAML → security/cost/best practice findings. | No            |
| `cip_analyze`| Deep analysis (RAG + tools + inspection) → summary + findings + sources.    | Yes           |

## Requirements

- **CIP API running** at `http://localhost:8000` (required for `cip_ask` and
  `cip_analyze`; optional for `cip_inspect`).

  ```powershell
  # inside the project directory
  uvicorn cip.api.app:app --host 0.0.0.0 --port 8000
  # or: make up
  ```

- Python 3.11+ with the package installed (`pip install -e .`) and the `mcp`
  SDK (`pip install mcp`). The server also works **without** the `mcp` SDK:
  there is a fallback to the stdio JSON-RPC 2.0 protocol implemented manually.

- API URL configurable via env `CIP_API_BASE_URL` (default
  `http://localhost:8000`).

## Standalone execution

```powershell
python -m cip.mcp_server
```

The process reads JSON-RPC 2.0 from stdin and responds on stdout (stdio protocol).

## Editor configuration

Use the `mcp-config.json` file at the project root:

```json
{
  "mcpServers": {
    "cip": {
      "command": "C:\\Python314\\python.exe",
      "args": ["-m", "cip.mcp_server"],
      "env": {
        "CIP_API_BASE_URL": "http://localhost:8000",
        "PYTHONPATH": "C:\\Projetos\\cip\\src"
      }
    }
  }
}
```

### Cursor

1. `Settings > Cursor Settings > MCP`.
2. Click **Add new MCP server**.
3. Name: `cip`. Type: `command`. Command:
   `python -m cip.mcp_server` (with the project directory in PATH/cwd, or use
   the absolute Python path).
4. Alternatively, point to the project's `mcp-config.json`.

### Kiro

1. In the project directory, Kiro consumes `.mcp.json` or `mcp-config.json`.
2. Make sure `command` points to a `python` that has the `cip` package and
   dependencies installed.

### Claude Desktop

1. Open `~/.config/Claude/claude_desktop_config.json` (macOS/Linux) or
   `%APPDATA%\Claude\claude_desktop_config.json` (Windows).
2. Add the `cip` block (same content as `mcp-config.json`).
3. Restart Claude Desktop.

## Usage examples

### `cip_ask`

```text
Question: "How to reduce cost of an S3 bucket with cold data?"
→ RAG query with sources (text response + **Sources:** at the end).
```

### `cip_inspect`

```text
Payload (Terraform):
  resource "aws_s3_bucket" "data" { bucket = "my-data" }
→ list of findings (title, severity, domain, description, recommendation, ...).
```

```text
Payload (Kubernetes):
  kind: Deployment ... securityContext: { privileged: true }
→ security findings (critical), reliability and operations.
```

### `cip_analyze`

```text
Question: "Review this RDS Terraform for production" + iac_payload inline
→ { summary, intent, clouds, findings (prioritized), sources, tools_used }.
```

## Design decisions

- `cip_ask` / `cip_analyze` call the REST API via `httpx` to **avoid** importing
  the async RAG/orchestrator stack into the MCP process (project requirement).
- `cip_inspect` calls `cip.inspection.engine.inspect_payload()` directly
  (synchronous, no heavy dependencies).
- Manual stdio JSON-RPC 2.0 fallback in case the `mcp` SDK is not installed.

## Tests

```powershell
python -m pytest tests/test_mcp_server.py -v
```
