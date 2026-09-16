# OMA Fetcher

OMA Fetcher is a single-URL Web Reader and discovery API. It keeps discovery,
fetching, and content extraction separate:

```text
robots.txt / sitemap discovery
              ↓
httpx → curl-cffi → Scrapling → Playwright
              ↓
         Trafilatura extraction
```

The API does not persist fetched content. It returns an envelope for every
outcome:

```json
{"code": 0, "message": "ok", "data": "...", "meta": {}}
```

`code: 0` means success. On an error, `data` is `null` and `message` plus
`meta.attempts` explain the failure.

## Quickstart

This project uses [uv](https://docs.astral.sh/uv/) for Python dependencies.

```sh
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
curl -sS http://127.0.0.1:8000/healthz | jq
```

If port 8000 is already in use, choose another port such as 8003 and use that
port in the commands below. Interactive OpenAPI documentation is available at
`/docs`.

## Docker deployment

Docker builds the browser-enabled runtime, including Chromium, Playwright, and
Scrapling dependencies:

```sh
docker compose up -d --build
docker compose ps
curl -sS http://127.0.0.1:8000/healthz | jq
```

Follow logs with:

```sh
docker compose logs -f fetcher
```

Stop the deployment with `docker compose down`.

### Colima and proxy configuration

When Docker needs a proxy, it must be reachable from the Colima VM/container.
macOS `127.0.0.1:7897` is not automatically reachable inside a container.
Provide a reachable proxy endpoint explicitly:

```sh
export FETCHER_BUILD_PROXY=http://REACHABLE_PROXY_HOST:7897
export FETCHER_RUNTIME_PROXY=http://REACHABLE_PROXY_HOST:7897
docker compose up -d --build
```

Host-side `http_proxy=http://127.0.0.1:7897` can still help local tools, but
Compose intentionally does not forward it into the container.

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/fetch` | Fetch one URL and extract Markdown, text, JSON, or XML. |
| `GET /api/robots?url=…` | Read an origin's raw `robots.txt`. |
| `GET /api/sitemap?url=…` | Find and expand sitemap documents into page URLs. |

### Fetch a page

Markdown is the default. Supported `output_format` values are `markdown`,
`txt`, `json`, and `xml`.

```sh
curl -sS --fail-with-body -X POST 'http://127.0.0.1:8000/api/fetch' \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://www.iso.org/standard/87210.html",
    "output_format": "markdown",
    "timeout_seconds": 90
  }' \
  | jq -e 'if .code == 0 then .data else error(.message) end'
```

Inspect extraction and fallback details without printing the entire page:

```sh
curl -sS -X POST 'http://127.0.0.1:8000/api/fetch' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.iso.org/standard/87210.html","timeout_seconds":90}' \
  | jq '{code, message, strategy: .meta.strategy, final_url: .meta.final_url, attempts: .meta.attempts}'
```

### Read robots.txt

```sh
curl -sS --fail-with-body --get 'http://127.0.0.1:8000/api/robots' \
  --data-urlencode 'url=https://www.iso.org/' \
  | jq -e 'if .code == 0 then .data else error(.message) end'
```

### List sitemap URLs

`data` is a JSON-encoded string array; use `fromjson` to turn it into an array
for jq processing.

```sh
curl -sS --fail-with-body --get 'http://127.0.0.1:8000/api/sitemap' \
  --data-urlencode 'url=https://www.iso.org/sitemap/standard.xml' \
  | jq -e 'if .code == 0 then .data | fromjson[:20][] else error(.message) end'
```

## Failback and observability

`/api/fetch` escalates from `httpx` to `curl-cffi`, Scrapling stealth, and
finally Playwright. It also escalates if Trafilatura cannot extract meaningful
main content.

Discovery endpoints use `httpx → curl-cffi → Scrapling`, then retry the whole
chain with bounded jitter. This matters for sites whose WAF returns an
intermittent 403, such as ISO.

Each result exposes the full attempt trace:

```sh
curl -sS --get 'http://127.0.0.1:8000/api/robots' \
  --data-urlencode 'url=https://www.iso.org/' \
  | jq '{code, message, attempts: .meta.attempts}'
```

Example successful trace:

```json
{
  "code": 0,
  "attempts": [
    {"strategy": "httpx", "round": 1, "status_code": 403},
    {"strategy": "curl_cffi", "round": 1, "status_code": 200}
  ]
}
```

Service logs use `discovery.fetch` records and include the strategy, round,
HTTP status, and errors. If a client prints `null`, inspect the entire envelope
rather than treating it as extracted content:

```sh
curl -sS --get 'http://127.0.0.1:8000/api/robots' \
  --data-urlencode 'url=https://www.iso.org/' \
  | jq '{code, message, attempts: .meta.attempts}'
```

## Project skill

Agent instructions and reusable curl workflows live in
[`.agents/skills/oma-fetcher/SKILL.md`](.agents/skills/oma-fetcher/SKILL.md).
The adjacent `evals/evals.json` captures representative robots, sitemap, and
failback-diagnosis prompts for future skill evaluation.

## Safety defaults

Private, loopback, link-local, multicast, and other non-routable targets are
rejected by default. `/api/fetch` enforces robots rules by default. Configure
the documented variables in `.env.example` only for a trusted deployment.
