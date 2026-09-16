# OMA Fetcher

OMA Fetcher is a single-URL Web Reader and discovery API. It keeps discovery,
fetching, and content extraction separate:

For all request parameters, output values, and response fields, see the
[API Reference](docs/api-reference.md).

```text
robots.txt / sitemap discovery
              ↓
httpx → curl-cffi → Scrapling → Playwright
              ↓
         Trafilatura extraction
```

The API fetches without persistence by default and can opt into a local SQLite
document store per request. It returns an envelope for every outcome:

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
`/docs`. The optional static Web UI is served at `http://127.0.0.1:8080`.
To inspect the script before running it:

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
bin/ops.sh restart
bin/ops.sh stop

bin/ops.sh start -p 8003         # choose a different local port
bin/ops.sh status -p 8003
bin/ops.sh restart -p 8003
bin/ops.sh stop -p 8003
```

In another terminal:

```sh
curl -sS http://127.0.0.1:7890/healthz | jq
```

### Health probes

Use the specific endpoint which matches the caller's purpose. HTTP status is
the primary signal: `200` is healthy/ready and `503` means not ready.

| Endpoint | Use |
| --- | --- |
| `/livez` | Process liveness only; no SQLite or external dependency check. |
| `/readyz` | Ready to serve requests; verifies the SQLite Document Store initialized. |
| `/healthz` | Compatibility alias for `/readyz`. |
| `/health` | Compatibility alias for `/readyz`. |

```sh
curl -fsS http://127.0.0.1:7890/livez | jq
curl -fsS http://127.0.0.1:7890/readyz | jq
```

Open `http://127.0.0.1:8080` for the separate Reader library UI. It provides
Dataset and Keys pages, Bearer-key reuse, table filtering/pagination, document
details/delete, and key create/copy/revoke.

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
| `POST /api/search` | Search persisted documents with jieba and FTS5. |
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

### Persist a fetched document

Fetching is non-persistent by default. To store the original extracted content,
page metadata, FTS tokens, and fetch history in SQLite, opt in per request:

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/fetch?persist=true' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.samr.gov.cn/hd/zjdc/","timeout_seconds":90}' \
  | jq '{code, storage: .meta.storage}'
```

The standards-based header alternative is `Prefer: persist`; a successful
response includes `Preference-Applied: persist`.

```sh
curl -i -sS -X POST 'http://127.0.0.1:7890/api/fetch' \
  -H 'Content-Type: application/json' \
  -H 'Prefer: persist' \
  -d '{"url":"https://example.com/"}'
```

Priority is `persist` query parameter, then `Prefer: persist`, then
`STORAGE_SAVE_DEFAULT=off|on` in `.env`. Content is de-duplicated by SHA-256;
repeated content reuses its document while recording another fetch history row.

### Search stored documents

Search uses jieba tokenization and SQLite FTS5 with title, description, tags,
and content weights of 5, 2, 3, and 1 respectively.

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

Search `data` is a JSON array of title, URL, hostname, publication date, BM25
score, and FTS snippet. Original document text is retained in SQLite; only the
separate search projection is jieba-tokenized.

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

### Smart failback

HTTP success is not treated as content success. The assessor distinguishes
article text, rendered listing cards, robots directives, and sitemap XML from
cookie/browser fallback text, empty 202 responses, and anti-bot placeholders.
For example, an ITU news-listing page whose Trafilatura output is a browser
support message is rendered as a Markdown card list instead of being stored as
that message.

Successful routes are cached in SQLite by normalized hostname and target kind
(`page`, `robots`, or `sitemap`) for seven days by default. The next request
starts with the most recently successful strategy; if it fails, the cache entry
is expired and the complete failback chain resumes. Configure the route TTL:

```dotenv
FETCH_ROUTE_TTL_HOURS=168
```

`meta.failback` provides non-sensitive diagnostics:

```json
{
  "route_hit": true,
  "preferred_strategy": "httpx",
  "accepted_strategy": "httpx",
  "signals": ["rendered_article_cards"]
}
```

Discovery endpoints use `httpx → curl-cffi → Scrapling HTTP → Scrapling stealth
browser`, then retry the whole chain with bounded jitter. The browser stage is
only launched when the lighter strategies cannot return an actual robots or
sitemap document, such as IEC's empty HTTP 202 placeholder response.

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

## API authentication

API authentication is opt-in for local development and should be enabled when
the service is reachable beyond localhost:

```dotenv
API_AUTH_ENABLED=on
API_ADMIN_KEY=<at-least-32-random-characters>
API_KEY_PEPPER=<different-at-least-32-random-secret>
```

When enabled, all `/api/*` endpoints require `Authorization: Bearer <token>`.
Health probes remain anonymous. `API_ADMIN_KEY` exists only in the environment;
client keys created through `/api/keys` are shown once and stored in SQLite only
as HMACs.

Create and manage client keys with the administrator key:

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/keys' \
  -H "Authorization: Bearer $API_ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"name":"research-agent","scopes":["fetch","search"]}' | jq

curl -sS 'http://127.0.0.1:7890/api/keys' \
  -H "Authorization: Bearer $API_ADMIN_KEY" | jq
```

Treat the returned client token like a password; it cannot be recovered after
the create response. Do not put keys in query strings or commit them to `.env`.

## Document store configuration

The direct-development database defaults to `data/research.db`; `data/` is
ignored by Git. Docker Compose bind-mounts `./data:/data`, so normal container
stop, restart, and Compose teardown do not remove the database.

SQLite uses WAL mode, `synchronous=NORMAL`, foreign keys, and a 5-second busy
timeout. Use `dictionaries/custom.txt` to add jieba user words; it is mounted
read-only at `/dictionaries/custom.txt` in Docker and is loaded at startup when
non-empty.

```dotenv
# .env
STORAGE_SAVE_DEFAULT=off
```
