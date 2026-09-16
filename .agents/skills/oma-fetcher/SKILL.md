---
name: oma-fetcher
description: Use the OMA Fetcher FastAPI service to retrieve a single URL as clean Markdown, text, JSON, or XML; inspect robots.txt; discover sitemap URLs; and diagnose fetch escalation. Use this skill whenever a user asks to fetch/read/extract a web page through this project, inspect robots.txt, list sitemap URLs, test `/api/fetch`, `/api/robots`, or `/api/sitemap`, or investigate `data: null` / 403 / WAF fallback behavior.
compatibility: Requires curl, jq, and a running OMA Fetcher service.
---

# OMA Fetcher

Use this project as a single-URL reader and discovery service. It returns a
consistent JSON envelope:

```json
{"code": 0, "message": "ok", "data": "...", "meta": {}}
```

`code: 0` is the success criterion. Do not treat a printed `null` from
`jq -r '.data'` as successful output; it means the API returned an error
envelope with no data.

## Establish the service URL

Use the caller-provided service URL when available. Otherwise use:

```sh
export OMA_FETCHER_BASE_URL="http://127.0.0.1:7890"
```

If port 7890 is occupied, start the project on another port and update the
variable:

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 8003
export OMA_FETCHER_BASE_URL="http://127.0.0.1:8003"
```

For a managed background local instance, use `bin/ops.sh`. Its default is 7890
and it supports `start`, `stop`, `restart`, and `status` plus `-p PORT`:

```sh
bin/ops.sh start -p 8003
export OMA_FETCHER_BASE_URL="http://127.0.0.1:8003"
bin/ops.sh status -p 8003
```

Check health before making a request:

```sh
curl -sS --fail-with-body "$OMA_FETCHER_BASE_URL/healthz" | jq
```

## Deploy on a new macOS machine

The repository ships a one-command installer for users who have not installed
Homebrew, Docker CLI, or Colima. It pulls the published GHCR image and never
performs a local Docker build:

```sh
curl -fsSL https://raw.githubusercontent.com/wyf0931/oma-fetcher/main/scripts/install-macos.sh | bash
```

The script defaults to `~/oma-fetcher` and port 7890. Docker Compose reads
`PROXY_ENABLED=off|on` and `PROXY_URL` from `.env`; when enabled it applies the
same proxy URL to all fetch strategies. Keep credentials in the ignored `.env`
file, not in commands, logs, or source control. macOS `127.0.0.1` proxies are
not automatically reachable from Colima containers.

## Fetch and extract one page

Markdown is the default output. Always inspect the response envelope before
printing a large body or reporting success.

```sh
curl -sS --fail-with-body -X POST "$OMA_FETCHER_BASE_URL/api/fetch" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/article","output_format":"markdown","timeout_seconds":90}' \
  | jq '{code, message, strategy: .meta.strategy, attempts: .meta.attempts}'
```

To print extracted Markdown only after confirming success:

```sh
curl -sS --fail-with-body -X POST "$OMA_FETCHER_BASE_URL/api/fetch" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/article","output_format":"markdown","timeout_seconds":90}' \
  | jq -e 'if .code == 0 then .data else error(.message) end'
```

Set `output_format` to `txt`, `json`, or `xml` when the caller needs a
Trafilatura format other than Markdown. Do not use `strategy` unless diagnosing
a particular layer; `auto` is the normal choice.

Every successful fetch returns Trafilatura's semantic metadata directly in
`meta.page`: title, author, description, date, sitename, categories,
tags, image, language, page type, URL, hostname, fingerprint, ID, and license.
Keep content in `data` and inspect metadata separately:

```sh
curl -sS -X POST "$OMA_FETCHER_BASE_URL/api/fetch" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/article","timeout_seconds":90}' \
  | jq '.meta.page'
```

## Persist and search documents

Fetches are not stored by default. Add `?persist=true` to persist a document,
its jieba search projection, and fetch history. The response reports
`meta.storage.document_id` and `meta.storage.deduplicated`.

```sh
curl -sS -X POST "$OMA_FETCHER_BASE_URL/api/fetch?persist=true" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/article"}' \
  | jq '{code, storage: .meta.storage}'
```

`Prefer: persist` is the HTTP-header alternative. Query `persist=true|false`
overrides that header, which overrides `.env` `STORAGE_SAVE_DEFAULT`.

Search persisted documents with title/tag/content FTS matching and optional
hostname/date filters:

```sh
curl -sS -X POST "$OMA_FETCHER_BASE_URL/api/search" \
  -H 'Content-Type: application/json' \
  -d '{"query":"国家标准 外文版","hostname":"samr.gov.cn","limit":20}' \
  | jq '.data'
```

## Read robots.txt

```sh
curl -sS --fail-with-body --get "$OMA_FETCHER_BASE_URL/api/robots" \
  --data-urlencode 'url=https://www.iso.org/' \
  | jq -e 'if .code == 0 then .data else error(.message) end'
```

To inspect the path taken through the fallback chain:

```sh
curl -sS --get "$OMA_FETCHER_BASE_URL/api/robots" \
  --data-urlencode 'url=https://www.iso.org/' \
  | jq '{code, message, attempts: .meta.attempts}'
```

## Discover sitemap URLs

Pass a domain, normal page URL, or direct sitemap URL. The `data` field is a
JSON-encoded string, so decode it with `fromjson` before iterating.

```sh
curl -sS --fail-with-body --get "$OMA_FETCHER_BASE_URL/api/sitemap" \
  --data-urlencode 'url=https://www.iso.org/sitemap/standard.xml' \
  | jq -e 'if .code == 0 then .data | fromjson[:20][] else error(.message) end'
```

For counts and source documents:

```sh
curl -sS --get "$OMA_FETCHER_BASE_URL/api/sitemap" \
  --data-urlencode 'url=https://www.iso.org/' \
  | jq '{code, message, count: .meta.count, sitemaps: .meta.sitemaps, robots: .meta.robots}'
```

## Diagnose fallback behavior

Discovery follows `httpx → curl-cffi → Scrapling HTTP → Scrapling stealth
browser` and retries the complete chain with bounded jitter. An empty HTTP 202
is not treated as a robots/sitemap success; it escalates to the next strategy.
Page fetching additionally escalates to Playwright. Every completed attempt
appears in `meta.attempts`; server logs contain matching `discovery.fetch`
records.

- `data: null` plus nonzero `code` means all eligible attempts failed or a
  policy check rejected the request. Report `message` and `meta.attempts`.
- A 403 in an earlier attempt is expected for protected sites if a later stage
  succeeds. Report the winning `strategy`, not the earlier 403 as final failure.
- Read `meta.failback` when present. It reports whether a cached
  hostname/target-kind route was used, which strategy was accepted, and safe
  quality signals such as `rendered_article_cards`; it never includes proxy
  settings or credentials.
- A 200 response can still be rejected when it contains cookie/browser fallback
  text. Listing pages can instead return Markdown extracted from rendered
  article cards, with `meta.content_kind` set to `listing`.
- Do not retry aggressively from the shell. The service already applies
  bounded retries; repeated manual calls can increase WAF rate limiting.
- The service rejects private, loopback, and non-routable URLs by default.
  Do not recommend disabling this outside a trusted network.
