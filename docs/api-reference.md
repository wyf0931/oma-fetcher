# API Reference

Base URL for local development: `http://127.0.0.1:7890`.

All responses use:

```json
{"code": 0, "message": "ok", "data": "...", "meta": {}}
```

Nonzero `code` indicates an application error. Use the HTTP status first for
health probes and transport handling.

## `POST /api/fetch`

Fetch, assess, extract, and optionally persist one URL.

### JSON body

| Field | Type | Default | Values / notes |
| --- | --- | --- | --- |
| `url` | URL | required | Absolute HTTP or HTTPS URL. |
| `output_format` | string | `markdown` | `markdown`, `txt`, `json`, `xml`. |
| `timeout_seconds` | integer | `45` | 3–180 seconds, shared across failback stages. |
| `strategy` | string | `auto` | `auto`, `httpx`, `curl_cffi`, `scrapling`, `playwright`. |

### Persistence controls

| Mechanism | Example | Priority |
| --- | --- | --- |
| Query parameter | `?persist=true` or `?persist=false` | 1 |
| HTTP header | `Prefer: persist` | 2 |
| Environment | `STORAGE_SAVE_DEFAULT=on` | 3 |

When persistence succeeds, a `Prefer: persist` request receives
`Preference-Applied: persist`. `meta.storage` reports `document_id` and
`deduplicated`.

### Content formats

Article content is rendered by Trafilatura. Smart Failback may classify a page
as a listing and extract article cards; listings honor the same format:

| Format | `data` value |
| --- | --- |
| `markdown` | Markdown headings and links. |
| `txt` | Plain-text listing title, item titles, URLs, and dates. |
| `json` | JSON string containing `title` and `items`. |
| `xml` | XML string rooted at `<listing>`. |

### Relevant metadata

`meta.page` contains Trafilatura metadata. `meta.content_kind` is `article` or
`listing`; `meta.extraction_method` identifies `trafilatura` or
`article_cards`; `meta.failback` shows a safe route decision trace.

## `POST /api/search`

Search persisted documents using jieba tokens and SQLite FTS5.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `query` | string | required | 1–500 characters. |
| `hostname` | string | none | Exact hostname filter. |
| `published_after` | date | none | Inclusive `YYYY-MM-DD`. |
| `published_before` | date | none | Inclusive `YYYY-MM-DD`. |
| `limit` | integer | `20` | 1–100. |

`data` is a JSON array. Result fields include `id`, `title`, `url`,
`canonical_url`, `hostname`, `published_at`, BM25 `score`, and FTS `snippet`.

## `GET /api/robots?url=…`

Retrieves an origin's raw robots content. `data` is the raw text. Discovery
uses Smart Failback and only accepts HTTP 200 with nonempty content, or an
explicit 404. `meta.attempts` lists strategy decisions.

## `GET /api/sitemap?url=…`

Accepts a site URL, page URL, or sitemap URL. `data` is a JSON-encoded array
of discovered page URLs; use `jq '.data | fromjson'`. `meta` includes sitemap
documents, count, truncation state, and robots discovery details.

## Health endpoints

| Endpoint | `200` means | `503` means |
| --- | --- | --- |
| `/livez` | Process can respond. | Not applicable under normal operation. |
| `/readyz` | SQLite store initialized and service is ready. | Store unavailable. |
| `/healthz` | Alias of `/readyz`. | Store unavailable. |
| `/health` | Alias of `/readyz`. | Store unavailable. |
