# OMA Fetcher

**English** · [简体中文](README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Container](https://img.shields.io/badge/GHCR-ghcr.io%2Fwyf0931%2Foma--fetcher-2496ed?logo=docker&logoColor=white)](https://github.com/wyf0931/oma-fetcher/pkgs/container/oma-fetcher)
[![Release](https://img.shields.io/github/v/release/wyf0931/oma-fetcher?display_name=tag)](https://github.com/wyf0931/oma-fetcher/releases)

OMA Fetcher is a single-URL **Web Reader and discovery API**. It turns one URL
into clean Markdown, text, JSON, or XML; reads `robots.txt`; discovers sitemap
URLs; and can persist documents to a local SQLite library.

It is built for agents and tools that need reliable page content without a
browser automation framework in every caller.

## Features

- **One URL in, clean content out** — Trafilatura extraction with
  `markdown`, `txt`, `json`, and `xml` output.
- **Progressive failback** — `httpx` → `curl-cffi` → Scrapling stealth →
  Playwright, with a shared timeout budget.
- **Content-aware assessment** — detects articles, listing cards, robots and
  sitemap documents, cookie/browser fallback text, and anti-bot placeholders.
- **Robots and sitemap discovery** — raw `robots.txt` access and bounded
  sitemap expansion.
- **Optional persistence and search** — SQLite document store with
  jieba + FTS5 search; fetching stays non-persistent unless you opt in.
- **Safety defaults** — private/loopback targets rejected and robots rules
  enforced by default.
- **Local Reader UI** — browse the document library and manage API keys.
- **Single container** — published to GHCR with Chromium and all fetch
  strategies included.

## How it works

```text
robots.txt / sitemap discovery
              ↓
httpx → curl-cffi → Scrapling → Playwright
              ↓
    content assessment + Trafilatura extraction
              ↓
   markdown / txt / json / xml (+ optional SQLite)
```

Every response uses the same envelope:

```json
{"code": 0, "message": "ok", "data": "...", "meta": {}}
```

`code: 0` means success. On an error, `data` is `null` and `message` plus
`meta.attempts` explain what happened.

## Quickstart

### macOS one-command install

For a fresh macOS machine, the installer adds Homebrew, Git, Docker
CLI/Compose, and Colima only when missing, starts Colima, and pulls the
published image. It never builds an image locally.

```sh
curl -fsSL https://raw.githubusercontent.com/wyf0931/oma-fetcher/main/scripts/install-macos.sh | bash
```

The service and Web UI are at `http://127.0.0.1:7890` (UI at `/`, API docs at
`/docs`). See [Deployment](docs/deployment.md) for options and safe overrides.

### Docker Compose

```sh
cp .env.example .env
docker compose pull
docker compose up -d
curl -sS http://127.0.0.1:7890/healthz | jq
```

### Local Python development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 7890
```

Or manage the API and Web UI together:

```sh
bin/ops.sh start                 # http://127.0.0.1:7890
bin/ops.sh status
bin/ops.sh stop
```

## Usage

### Fetch a page

Markdown is the default output format.

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/fetch?persist=true' \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://www.iso.org/standard/87210.html",
    "output_format": "markdown",
    "timeout_seconds": 90
  }' \
  | jq -e 'if .code == 0 then .data else error(.message) end'
```

Inspect the fetch decision without printing the page:

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/fetch' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.iso.org/standard/87210.html","timeout_seconds":90}' \
  | jq '{code, message, strategy: .meta.strategy, attempts: .meta.attempts}'
```

Persistence is opt-in. Use `?persist=true`, `Prefer: persist`, or
`STORAGE_SAVE_DEFAULT=on`; the query parameter wins. Successful responses also
include Trafilatura metadata in `meta.page`.

### Read robots.txt and sitemaps

```sh
curl -sS --get 'http://127.0.0.1:7890/api/robots' \
  --data-urlencode 'url=https://www.iso.org/' \
  | jq -e 'if .code == 0 then .data else error(.message) end'
```

```sh
curl -sS --get 'http://127.0.0.1:7890/api/sitemap' \
  --data-urlencode 'url=https://www.iso.org/sitemap/standard.xml' \
  | jq -e 'if .code == 0 then .data | fromjson[:20][] else error(.message) end'
```

### Search the document library

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/search' \
  -H 'Content-Type: application/json' \
  -d '{"query":"国家标准 外文版","limit":20}' | jq
```

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/fetch` | Fetch one URL and extract Markdown, text, JSON, or XML. |
| `POST /api/search` | Search persisted documents with jieba and FTS5. |
| `GET /api/documents` | List persisted documents with filters and pagination. |
| `GET /api/documents/{id}` | Read one document and its fetch history. |
| `DELETE /api/documents/{id}` | Delete a document. |
| `GET /api/robots?url=…` | Read an origin's raw `robots.txt`. |
| `GET /api/sitemap?url=…` | Expand sitemap documents into page URLs. |
| `GET/PUT/DELETE /api/settings/proxy` | Inspect or override the active proxy. |
| `POST/GET/DELETE /api/keys` | Manage client API keys. |
| `GET /livez`, `/readyz`, `/healthz`, `/health` | Liveness and readiness probes. |

Full request fields, response metadata, and error codes are in the
[API Reference](docs/api-reference.md).

## Web UI

Open `http://127.0.0.1:7890/` for the Reader library. It provides Dataset and
Keys pages, Bearer-key reuse, table filtering/pagination, document
details/delete, and key create/copy/delete. Proxy settings can be changed from
the settings panel without restarting the service.

## Configuration

Copy `.env.example` to `.env` and set only what you need. Common options:

| Variable | Default | Purpose |
| --- | --- | --- |
| `FETCHER_ENFORCE_ROBOTS` | `true` | Respect robots rules for page fetches. |
| `FETCHER_ALLOW_PRIVATE_NETWORKS` | `false` | Allow private/loopback targets. |
| `STORAGE_SAVE_DEFAULT` | `off` | Persist every fetch unless overridden. |
| `FETCH_ROUTE_TTL_HOURS` | `168` | Route-cache TTL per hostname and target kind. |
| `PROXY_ENABLED` / `PROXY_URL` | `off` / empty | Route all strategies through a proxy. |
| `API_AUTH_ENABLED` | `off` | Require Bearer tokens for `/api/*`. |
| `API_ADMIN_KEY` / `API_KEY_PEPPER` | empty | Administrator token and key-hash pepper. |
| `API_DOCS_ENABLED` | `true` | Serve `/docs` and `/redoc`. |

See [Configuration](docs/configuration.md) for every variable, persistence
precedence, proxy overrides, and authentication setup.

## Deployment

The published image is `ghcr.io/wyf0931/oma-fetcher`. Deployments pull it from
GitHub Container Registry rather than building locally.

```sh
docker compose pull
docker compose up -d
docker compose logs -f fetcher
```

Health probes are anonymous even when authentication is enabled. Use `/livez`
for process liveness and `/readyz` for readiness. See
[Deployment](docs/deployment.md) for image tags, upgrades, rollback, Colima,
and security hardening.

## Failback and observability

HTTP success is not treated as content success. `/api/fetch` escalates from
`httpx` to `curl-cffi`, Scrapling stealth, and Playwright, and also escalates
when Trafilatura cannot extract meaningful main content. Successful routes are
cached by hostname and target kind for seven days by default.

Each response exposes `meta.attempts` and `meta.failback`. If a client prints
`null`, inspect the entire envelope rather than treating it as content. See
[Failback and observability](docs/failback.md) for the assessment rules,
discovery retries, and troubleshooting table.

## Documentation

| Document | Contents |
| --- | --- |
| [README.zh-CN.md](README.zh-CN.md) | 中文说明 |
| [docs/api-reference.md](docs/api-reference.md) | Endpoints, fields, formats, error codes. |
| [docs/configuration.md](docs/configuration.md) | Environment variables, storage, proxy, auth. |
| [docs/deployment.md](docs/deployment.md) | Install, Docker, upgrades, health, security. |
| [docs/failback.md](docs/failback.md) | Escalation, assessment, diagnostics. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup, tests, project layout. |
| [.agents/skills/oma-fetcher/SKILL.md](.agents/skills/oma-fetcher/SKILL.md) | Agent quickstart and curl workflows. |

## Third-party licenses

OMA Fetcher is MIT-licensed. Its main dependencies and vendored browser assets
use these licenses:

| Component | License | Role |
| --- | --- | --- |
| [Python](https://www.python.org/) 3.12+ | PSF-2.0 | Runtime. |
| [FastAPI](https://github.com/fastapi/fastapi) / [Pydantic](https://github.com/pydantic/pydantic) | MIT | HTTP API and models. |
| [Uvicorn](https://github.com/Kludex/uvicorn) / [Starlette](https://github.com/Kludex/starlette) | BSD-3-Clause | ASGI server and framework. |
| [HTTPX](https://github.com/encode/httpx) | BSD-3-Clause | HTTP/2 and SOCKS support. |
| [curl-cffi](https://github.com/lexiforest/curl_cffi) | MIT | Browser-impersonating HTTP. |
| [Playwright](https://github.com/microsoft/playwright-python) | Apache-2.0 | Browser rendering. |
| [Scrapling](https://github.com/D4Vinci/Scrapling) | BSD-3-Clause | Stealth fetching and parsing. |
| [Trafilatura](https://github.com/adbar/trafilatura) | Apache-2.0 | Main-content extraction and metadata. |
| [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) | MIT | HTML parsing. |
| [jieba](https://github.com/fxsjy/jieba) | MIT | Chinese tokenization for FTS. |
| [PrismJS](https://prismjs.com/) (vendored) | MIT | JSON syntax highlighting. |
| [Lucide](https://lucide.dev/) (vendored) | ISC | UI icons. |

Transitive dependencies remain under their own licenses. When redistributing
the container image, retain the license notices shipped with those packages.

## Contributing

Issues and pull requests are welcome. Run `uv run pytest -q` before sending a
change, keep `README.md` and `README.zh-CN.md` in sync, and avoid committing
`.env`, databases, or credentials. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Scott
