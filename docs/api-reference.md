# API Reference

Base URL for local development: `http://127.0.0.1:7890`.

All JSON responses use the same envelope:

```json
{"code": 0, "message": "ok", "data": "...", "meta": {}}
```

`code: 0` means success. Nonzero `code` indicates an application error; `data`
is usually `null` and `meta` contains diagnostics. Use the HTTP status first
for transport and health handling, then `code` for application behavior.

Interactive OpenAPI documentation is available at `/docs` (and `/redoc`) when
`API_DOCS_ENABLED=true`.

## Authentication

Authentication is opt-in. When `API_AUTH_ENABLED=on`, every `/api/*` endpoint
requires:

```http
Authorization: Bearer <token>
```

Health probes (`/livez`, `/readyz`, `/healthz`, `/health`) remain anonymous.
Scopes are `fetch`, `search`, and `admin`; a request without the required scope
receives HTTP `403`. The environment `API_ADMIN_KEY` is an administrator token
and can call every endpoint. Client keys are created through `/api/keys`.

## `POST /api/fetch`

Fetch, assess, extract, and optionally persist one URL. Requires the `fetch`
scope.

### JSON body

| Field | Type | Default | Values / notes |
| --- | --- | --- | --- |
| `url` | URL | required | Absolute HTTP or HTTPS URL. Private/loopback targets are rejected unless `FETCHER_ALLOW_PRIVATE_NETWORKS=true`. |
| `output_format` | string | `markdown` | `markdown`, `txt`, `json`, `xml`. |
| `timeout_seconds` | integer | `45` | 3–180 seconds, shared across failback stages. |
| `strategy` | string | `auto` | `auto`, `httpx`, `curl_cffi`, `scrapling`, `playwright`. |

### Persistence controls

Fetching is non-persistent by default. Choose persistence with this priority:

| Mechanism | Example | Priority |
| --- | --- | --- |
| Query parameter | `?persist=true` or `?persist=false` | 1 |
| HTTP header | `Prefer: persist` | 2 |
| Environment | `STORAGE_SAVE_DEFAULT=on` | 3 |

When persistence succeeds, a `Prefer: persist` request receives
`Preference-Applied: persist`. `meta.storage` reports `requested`, `saved`,
`source`, `document_id`, and `deduplicated`. Content is de-duplicated by
SHA-256; repeated content reuses the existing document while recording another
fetch-history row.

### Content formats

Article content is rendered by Trafilatura. Smart Failback may classify a page
as a listing and extract article cards; listings honor the same format:

| Format | `data` value |
| --- | --- |
| `markdown` | Markdown headings and links. |
| `txt` | Plain-text listing title, item titles, URLs, and dates. |
| `json` | JSON string containing `title` and `items`. |
| `xml` | XML string rooted at `<listing>`. |

### Response metadata

| Field | Meaning |
| --- | --- |
| `meta.final_url` | URL after redirects. |
| `meta.strategy` | Strategy that produced the accepted response. |
| `meta.status_code` | Final HTTP status code. |
| `meta.content_type` | Final response content type. |
| `meta.attempts` | Ordered attempt trace: page fetches report `strategy` and `reason`; discovery attempts add `round`, `status_code`, and `error`. |
| `meta.proxy_enabled` | Whether a proxy was active for the request. |
| `meta.page` | Trafilatura metadata (see below). |
| `meta.content_kind` | `article` or `listing`. |
| `meta.extraction_method` | `trafilatura` or `article_cards`. |
| `meta.failback` | `route_hit`, `preferred_strategy`, `accepted_strategy`, `signals`. |
| `meta.storage` | Persistence result. |

`meta.page` includes title, author, date, description, sitename, categories,
tags, image, page type, language, URL, hostname, fingerprint, ID, and license.
The extracted Markdown/text remains in `data`.

### Examples

Fetch Markdown and print extracted content:

```sh
curl -sS --connect-timeout 5 --max-time 100 --fail-with-body \
  -X POST 'http://127.0.0.1:7890/api/fetch?persist=true' \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://www.iso.org/standard/87210.html",
    "output_format": "markdown",
    "timeout_seconds": 90
  }' \
  | jq -e 'if .code == 0 then .data else error(.message) end'
```

Inspect extraction and fallback details without printing the whole page:

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/fetch' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.iso.org/standard/87210.html","timeout_seconds":90}' \
  | jq '{code, message, strategy: .meta.strategy, final_url: .meta.final_url, attempts: .meta.attempts}'
```

Extract semantic page metadata:

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/fetch' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.iso.org/standard/87210.html","timeout_seconds":90}' \
  | jq '.meta.page | {title, author, date, description, sitename, categories, tags, image, pagetype, language, url}'
```

Persist with the standards-based header:

```sh
curl -i -sS -X POST 'http://127.0.0.1:7890/api/fetch' \
  -H 'Content-Type: application/json' \
  -H 'Prefer: persist' \
  -d '{"url":"https://example.com/"}'
```

Force one strategy:

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/fetch' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/","strategy":"httpx"}'
```

## `POST /api/search`

Search persisted documents using jieba tokens and SQLite FTS5. Requires the
`search` scope. Title, description, tags, and content weights are 5, 2, 3, and
1 respectively.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `query` | string | required | 1–500 characters. |
| `hostname` | string | none | Exact hostname filter. |
| `published_after` | date | none | Inclusive `YYYY-MM-DD`. |
| `published_before` | date | none | Inclusive `YYYY-MM-DD`. |
| `limit` | integer | `20` | 1–100. |

`data` is a JSON array. Result fields include `id`, `title`, `url`,
`canonical_url`, `hostname`, `published_at`, BM25 `score`, and FTS `snippet`.
Original document text is retained in SQLite; only the separate search
projection is jieba-tokenized.

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/search' \
  -H 'Content-Type: application/json' \
  -d '{
    "query":"国家标准 外文版",
    "hostname":"samr.gov.cn",
    "published_after":"2026-01-01",
    "published_before":"2026-12-31",
    "limit":20
  }' | jq
```

## Document management

The Web UI uses these CRUD endpoints. Listing and reading require
the `search` scope; deletion requires the `fetch` scope.

```text
GET    /api/documents?page=1&page_size=20&content=standard
GET    /api/documents/{id}
DELETE /api/documents/{id}
```

### `GET /api/documents`

| Query | Type | Default | Notes |
| --- | --- | --- | --- |
| `page` | integer | `1` | 1-based page. |
| `page_size` | integer | `20` | 1–100. |
| `title` | string | none | Substring filter. |
| `sitename` | string | none | Substring filter. |
| `tags` | string | none | Substring filter against stored tags. |
| `content` | string | none | Substring filter against title or content. |

`data` is an array of `id`, `title`, `url`, `site_name`, `hostname`,
`published_at`, `updated_at`, and `fetched_at`. `meta` contains `page`,
`page_size`, `total`, and `pages`.

### `GET /api/documents/{id}`

Returns the stored document, including `content`, parsed `tags`, `page`
metadata, and the fetch history in `fetches`. Returns `404` with `code: 4041`
when the document does not exist.

### `DELETE /api/documents/{id}`

Permanently deletes the document and its fetch history. Returns
`{"id": ..., "deleted": true}` or `404` with `code: 4041`.

## `GET /api/robots?url=…`

Retrieves an origin's raw robots content. Requires the `fetch` scope. `data` is
the raw text. Discovery uses Smart Failback and only accepts HTTP 200 with
nonempty content, or an explicit 404. `meta.attempts` lists strategy decisions.

```sh
curl -sS --fail-with-body --get 'http://127.0.0.1:7890/api/robots' \
  --data-urlencode 'url=https://www.iso.org/' \
  | jq -e 'if .code == 0 then .data else error(.message) end'
```

## `GET /api/sitemap?url=…`

Accepts a site URL, page URL, or sitemap URL. Requires the `fetch` scope. `data`
is a JSON-encoded array of discovered page URLs; use `jq '.data | fromjson'`.
`meta` includes sitemap documents, `count`, truncation state, and robots
discovery details.

```sh
curl -sS --fail-with-body --get 'http://127.0.0.1:7890/api/sitemap' \
  --data-urlencode 'url=https://www.iso.org/sitemap/standard.xml' \
  | jq -e 'if .code == 0 then .data | fromjson[:20][] else error(.message) end'
```

Discovery is bounded by `FETCHER_SITEMAP_MAX_URLS` (default 10000) and
`FETCHER_SITEMAP_MAX_DEPTH` (default 4). When the URL limit is reached,
`meta.truncated` is `true`.

## Proxy settings

These endpoints require the `admin` scope when authentication is enabled. They
are used by the Web UI settings panel. Credentials are never returned; the view
reports `username_configured` and `password_configured` instead.

### `GET /api/settings/proxy`

| Query | Values | Default | Notes |
| --- | --- | --- | --- |
| `source` | `active`, `environment` | `active` | `active` includes a saved override; `environment` shows the `.env` baseline. |

`data` contains `enabled`, `scheme`, `server`, `port`,
`username_configured`, `password_configured`, and `source`
(`override` or `environment`).

### `PUT /api/settings/proxy`

```json
{
  "enabled": true,
  "scheme": "http",
  "server": "proxy.example",
  "port": 8080,
  "username": "user",
  "password": "secret",
  "clear_credentials": false
}
```

Set `enabled: false` to force direct connections. When credentials are omitted,
existing credentials are reused unless `clear_credentials` is `true`. The
override is stored in SQLite and applied immediately to page, robots, and
sitemap requests.

### `DELETE /api/settings/proxy`

Removes the saved override and restores the `.env` baseline (`Use environment`
in the Web UI).

## API keys

These endpoints require the `admin` scope when authentication is enabled.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/keys` | Create a client key. |
| `GET` | `/api/keys` | List key metadata. |
| `DELETE` | `/api/keys/{id}` | Permanently delete a key. |

Create request:

```json
{"name": "research-agent", "scopes": ["fetch", "search"]}
```

`name` is 1–100 characters. `scopes` accepts `fetch`, `search`, and `admin`;
the default is `["fetch"]`. `expires_at` is an optional ISO-8601 datetime.

The create response contains the plaintext `token`, which is shown only once.
Keys are stored as HMACs; listing returns metadata such as `id`, `name`,
`key_prefix`, `key_suffix`, `scopes`, `created_at`, `expires_at`, `revoked_at`,
and `last_used_at`. Deleting a key physically removes it and immediately
invalidates it.

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/keys' \
  -H "Authorization: Bearer $API_ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"name":"research-agent","scopes":["fetch","search"]}' | jq

curl -sS 'http://127.0.0.1:7890/api/keys' \
  -H "Authorization: Bearer $API_ADMIN_KEY" | jq
```

## Health endpoints

| Endpoint | `200` means | `503` means |
| --- | --- | --- |
| `/livez` | Process can respond. | Not applicable under normal operation. |
| `/readyz` | SQLite store initialized and service is ready. | Store unavailable. |
| `/healthz` | Alias of `/readyz`. | Store unavailable. |
| `/health` | Alias of `/readyz`. | Store unavailable. |

Health probes are anonymous even when authentication is enabled.

## Error codes

| `code` | HTTP | Meaning |
| --- | --- | --- |
| `0` | `200` | Success. |
| `401` | `401` | Authentication required or invalid Bearer token. |
| `403` | `403` | Insufficient scope or non-administrator key. |
| `1001` | `422` | Invalid request body or query parameters. |
| `1002` | `400`/`422` | Unsafe URL or invalid proxy settings. |
| `2001` | `403` | Blocked by `robots.txt`. |
| `2002` | `422` | Page fetched but no main content could be extracted. |
| `2003` | `502` | All fetch strategies failed. |
| `3001` | `502` | Robots discovery failed. |
| `3002` | `404` | Sitemap discovery failed. |
| `4001` | `500` | Fetch succeeded but document storage failed. |
| `4002` | `503` | Document store unavailable. |
| `4003` | `503` | Service not ready. |
| `4004` | `503` | Settings or key storage failed. |
| `4040` | `404` | API key not found. |
| `4041` | `404` | Document not found. |

## MCP endpoint

The same process also serves MCP over Streamable HTTP at `POST /mcp` (and
`/mcp/`). Tools call the same fetch, discovery, and storage pipeline as the
REST endpoints and return the same `code` values. See
[MCP server](mcp.md) for client configuration, tool contracts, scopes, and
remote-host allowlists.

## Related documentation

- [Configuration](configuration.md)
- [Deployment](deployment.md)
- [Failback and observability](failback.md)
