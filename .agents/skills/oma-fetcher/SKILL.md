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
export OMA_FETCHER_BASE_URL="http://127.0.0.1:8000"
```

If port 8000 is occupied, start the project on another port and update the
variable:

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 8003
export OMA_FETCHER_BASE_URL="http://127.0.0.1:8003"
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

The script defaults to `~/oma-fetcher` and port 8000. Explain that macOS
`127.0.0.1` proxies are not automatically reachable from Colima containers;
use `FETCHER_RUNTIME_PROXY` only with an address reachable from that VM.

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

Every successful fetch also returns `meta.page_metadata`. It combines `html`
(raw SEO/OG/Twitter/canonical/hreflang/JSON-LD metadata) and `trafilatura`
(semantic title, author, date, sitename, categories, tags, image, language,
and page type). Keep content in `data` and inspect metadata separately:

```sh
curl -sS -X POST "$OMA_FETCHER_BASE_URL/api/fetch" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/article","timeout_seconds":90}' \
  | jq '.meta.page_metadata'
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

Discovery follows `httpx → curl-cffi → Scrapling` and retries the complete
chain with bounded jitter. Page fetching additionally escalates to the
Scrapling stealth browser and Playwright. Every completed attempt appears in
`meta.attempts`; server logs contain matching `discovery.fetch` records.

- `data: null` plus nonzero `code` means all eligible attempts failed or a
  policy check rejected the request. Report `message` and `meta.attempts`.
- A 403 in an earlier attempt is expected for protected sites if a later stage
  succeeds. Report the winning `strategy`, not the earlier 403 as final failure.
- Do not retry aggressively from the shell. The service already applies
  bounded retries; repeated manual calls can increase WAF rate limiting.
- The service rejects private, loopback, and non-routable URLs by default.
  Do not recommend disabling this outside a trusted network.
