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

### macOS one-command install (Colima)

For a fresh macOS machine, this downloads the versioned installer from this
repository. It installs Homebrew, Git, Docker CLI/Compose, and Colima only when
they are missing; starts Colima with a conservative 1 CPU / 2 GiB minimum; and
pulls the published GHCR image. It **does not build Docker images locally**.

```sh
curl -fsSL https://raw.githubusercontent.com/wyf0931/oma-fetcher/main/scripts/install-macos.sh | bash
```

The service is then available at `http://127.0.0.1:7890`, with API docs at
`/docs`. To inspect the script before running it:

```sh
curl -fsSLO https://raw.githubusercontent.com/wyf0931/oma-fetcher/main/scripts/install-macos.sh
less install-macos.sh
bash install-macos.sh
```

The script clones to `~/oma-fetcher` by default. Override its safe defaults:

```sh
FETCHER_DIR="$HOME/Developer/oma-fetcher" FETCHER_PORT=8003 \
  COLIMA_CPUS=2 COLIMA_MEMORY_GB=4 \
  bash scripts/install-macos.sh
```

It preserves a running Colima instance and refuses to overwrite a directory
that is not this repository or a port already in use.

### Local Python development

```sh
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 7890
```

For developer-local work, manage a background **non-Docker** instance with the
project helper. It runs `uvicorn` through `uv`, and stores its PID and logs in
the system temporary directory rather than the repository:

```sh
bin/ops.sh start                 # http://127.0.0.1:7890
bin/ops.sh status
bin/ops.sh stop

bin/ops.sh start -p 8003         # choose a different local port
bin/ops.sh status -p 8003
bin/ops.sh stop -p 8003
```

In another terminal:

```sh
curl -sS http://127.0.0.1:7890/healthz | jq
```

If port 7890 is already in use, choose another port such as 8003 and use that
port in the commands below. Interactive OpenAPI documentation is available at
`/docs`.

## Docker deployment

The published image contains Chromium, Playwright, and Scrapling dependencies.
Deployments pull it from GitHub Container Registry rather than building it on
your machine:

```sh
docker compose pull
docker compose up -d
docker compose ps
curl -sS http://127.0.0.1:7890/healthz | jq
```

Follow logs with:

```sh
docker compose logs -f fetcher
```

Stop the deployment with `docker compose down`.

### Colima and proxy configuration

When the running service needs a proxy, Docker Compose reads `PROXY_ENABLED`
and `PROXY_URL` from `.env`. The default is direct outbound traffic:

```sh
cp .env.example .env
# Edit .env only if a proxy is required.
PROXY_ENABLED=off
```

To force **every fetch strategy** through an authenticated proxy, set:

```sh
PROXY_ENABLED=on
PROXY_URL=http://USERNAME:PASSWORD@p.webshare.io:80/
```

Then restart the service:

```sh
docker compose pull
docker compose up -d --force-recreate
```

`PROXY_URL` is passed to HTTPX, curl-cffi, Scrapling, and Playwright. It is not
returned by the API or written to logs; logs redact the username and password.
Keep `.env` private. Use `.env.example` as the committed template. macOS
`127.0.0.1` proxies are not automatically reachable inside Colima containers.

To validate that the container exits through the proxy, fetch the Webshare IP
endpoint through the reader after enabling the proxy:

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/fetch' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://ipv4.webshare.io/","strategy":"httpx"}' \
  | jq '{code, proxy_enabled: .meta.proxy_enabled, ip: .data}'
```

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
curl -sS --fail-with-body -X POST 'http://127.0.0.1:7890/api/fetch' \
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
curl -sS -X POST 'http://127.0.0.1:7890/api/fetch' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.iso.org/standard/87210.html","timeout_seconds":90}' \
  | jq '{code, message, strategy: .meta.strategy, final_url: .meta.final_url, attempts: .meta.attempts}'
```

Successful fetch responses also contain Trafilatura's semantic metadata
directly in `meta.page`:

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/fetch' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.iso.org/standard/87210.html","timeout_seconds":90}' \
  | jq '.meta.page | {title, author, date, description, sitename, categories, tags, image, pagetype, language, url}'
```

Available fields include title, author, description, date, sitename, categories,
tags, image, page type, language, URL, hostname, fingerprint, ID, and license.
The extracted Markdown/text remains in `data`.

### Read robots.txt

```sh
curl -sS --fail-with-body --get 'http://127.0.0.1:7890/api/robots' \
  --data-urlencode 'url=https://www.iso.org/' \
  | jq -e 'if .code == 0 then .data else error(.message) end'
```

### List sitemap URLs

`data` is a JSON-encoded string array; use `fromjson` to turn it into an array
for jq processing.

```sh
curl -sS --fail-with-body --get 'http://127.0.0.1:7890/api/sitemap' \
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
curl -sS --get 'http://127.0.0.1:7890/api/robots' \
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
curl -sS --get 'http://127.0.0.1:7890/api/robots' \
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
