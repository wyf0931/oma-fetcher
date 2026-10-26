# MCP server

The Fetchly process is also an [MCP](https://modelcontextprotocol.io/) server.
Starting the normal service exposes **Streamable HTTP** at:

```text
http://127.0.0.1:7890/mcp
```

No second process, extra port, or sidecar is needed. The tools use the same
fetch pipeline, SQLite Results library, proxy, and authentication as `/api/*`.

## Copy-paste client config

Start the service first:

```sh
bin/ops.sh start
```

Then add this to your MCP client configuration (Claude Code `.mcp.json`,
Cursor `mcp.json`, or any client that reads `mcpServers`):

```json
{
  "mcpServers": {
    "fetchly": {
      "type": "http",
      "url": "http://127.0.0.1:7890/mcp"
    }
  }
}
```

Some clients reject the `type` field; omit it and keep `url`:

```json
{
  "mcpServers": {
    "fetchly": {
      "url": "http://127.0.0.1:7890/mcp"
    }
  }
}
```

VS Code uses a `servers` key instead of `mcpServers`:

```json
{
  "servers": {
    "fetchly": {
      "type": "http",
      "url": "http://127.0.0.1:7890/mcp"
    }
  }
}
```

Restart or reload the client, then call `fetchly_web_fetch` directly. Fetches
persist to the Results library by default, so `fetchly_search_results` and
`fetchly_get_result` work immediately.

### stdio fallback

For clients that only launch a command, run the same tools over stdio:

```json
{
  "mcpServers": {
    "fetchly": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/oma-fetcher",
        "python",
        "-m",
        "app.mcp_server"
      ]
    }
  }
}
```

stdio mode opens the SQLite store directly and does not need the HTTP service.

## Tools

Every tool returns the REST envelope shape, so the rules are the same as the
API: `code: 0` means success, `ok` is `code == 0`, and failures are returned as
values instead of exceptions.

```json
{"ok": true, "code": 0, "message": "ok"}
```

| Tool | Parameters | Returns |
| --- | --- | --- |
| `fetchly_web_fetch` | `url` (required), `output_format` = `markdown`, `timeout_seconds` = 90, `persist` = true, `strategy` = `auto` | Extracted `content` plus `final_url`, `strategy`, `status_code`, `content_kind`, `extraction_method`, `title`, `site_name`, `published_at`, `language`, `saved`, `document_id`, `deduplicated`, `attempts`, `signals`. |
| `fetchly_robots` | `url` (required) | Raw robots text in `content`, `found`, `status_code`, `url`, `attempts`. A missing file is `found: false`, not an error. |
| `fetchly_sitemap` | `url` (required), `max_urls` = 200 (1–10000) | `urls`, `total`, `returned`, `truncated`, `origin`, `sitemaps`. The tool truncates the server's full list before returning it. |
| `fetchly_search_results` | `query` (required), `hostname`, `published_after`, `published_before`, `limit` = 20 | `count` and `results` rows with `id`, `title`, `url`, `canonical_url`, `hostname`, `published_at`, `score`, and a highlighted `snippet`. |
| `fetchly_list_results` | `page` = 1, `page_size` = 20, `title`, `sitename`, `tags`, `content` | `page`, `page_size`, `total`, `pages`, and compact `results` rows. |
| `fetchly_get_result` | `document_id` (required) | `document` with full `content`, `tags`, semantic `page` metadata, and `fetches` history. Missing IDs return `code: 4041`. |

### Tool notes

- `fetchly_web_fetch` is the only tool that returns page content; it defaults to
  Markdown and a 90-second budget shared across fallback strategies.
- `persist: true` stores the page and returns `document_id`; pass `persist:
  false` for a one-off read.
- `fetchly_search_results`, `fetchly_list_results`, and `fetchly_get_result`
  read the same library that the Results page shows.
- `fetchly_sitemap` defaults to 200 URLs to protect the model context. Increase
  `max_urls` only when the caller can handle the larger list.
- Invalid arguments are rejected by the tool schema; service failures include
  `message` and, for fetches, `attempts`.

## Authentication and scopes

When `API_AUTH_ENABLED=on`, `/mcp` requires the same Bearer token as `/api/*`:

```json
{
  "mcpServers": {
    "fetchly": {
      "type": "http",
      "url": "http://127.0.0.1:7890/mcp",
      "headers": {
        "Authorization": "Bearer oma_your_client_token"
      }
    }
  }
}
```

Per-tool scopes match the REST endpoints:

| Scope | Tools |
| --- | --- |
| `fetch` | `fetchly_web_fetch`, `fetchly_robots`, `fetchly_sitemap` |
| `search` | `fetchly_search_results`, `fetchly_list_results`, `fetchly_get_result` |

Create a key with the scopes the agent needs; `POST /api/keys` defaults to
`["fetch"]`, so include `"search"` for library access. stdio clients have no
headers, so set `FETCHLY_MCP_TOKEN` to the Bearer token when authentication is
enabled.

## Remote access

MCP enables DNS-rebinding protection for localhost by default: any port on
`127.0.0.1`, `localhost`, or `[::1]`. When the service is reached by another
hostname, add it to the allowlist (comma-separated, `:*` allows any port):

```dotenv
FETCHLY_MCP_ALLOWED_HOSTS=example.com:*,192.168.1.10:*
FETCHLY_MCP_ALLOWED_ORIGINS=https://app.example.com
```

Restart the service after changing these values.

## Verify without a client

The initialize handshake is a normal JSON-RPC POST:

```sh
curl -sS -X POST 'http://127.0.0.1:7890/mcp' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

A successful response is an SSE `event: message` frame containing
`"serverInfo": {"name": "fetchly"}`. Interactive inspection is also possible
with `npx @modelcontextprotocol/inspector` pointed at the same URL.
