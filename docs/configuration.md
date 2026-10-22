# Configuration

OMA Fetcher is configured with environment variables. Copy `.env.example` to
`.env` and edit only the values you need. `.env` is loaded by Docker Compose and
by `bin/ops.sh`; plain `uv run uvicorn ...` does not load it automatically.

```sh
cp .env.example .env
```

> `.env` is ignored by Git. Never commit credentials, API keys, or proxy
> passwords.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `FETCHER_ALLOW_PRIVATE_NETWORKS` | `false` | Allow loopback, private, link-local, and other non-routable targets. Enable only in a trusted deployment. |
| `FETCHER_ENFORCE_ROBOTS` | `true` | Return a policy error when `robots.txt` disallows the requested page. |
| `FETCHER_MAX_RESPONSE_BYTES` | `5242880` | Maximum response body size (5 MiB). |
| `FETCHER_SITEMAP_MAX_URLS` | `10000` | Maximum URLs returned by sitemap expansion. |
| `FETCHER_SITEMAP_MAX_DEPTH` | `4` | Maximum nested sitemap depth. |
| `FETCHER_DISCOVERY_RETRIES` | `2` | Retry rounds for robots and sitemap discovery. |
| `FETCHER_DISCOVERY_RETRY_DELAY` | `0.4` | Base delay in seconds between discovery rounds. |
| `FETCHER_USER_AGENT` | `oma-fetcher/1.5` | User-Agent sent by fetch and discovery strategies. |
| `PROXY_ENABLED` | `off` | Route HTTPX, curl-cffi, Scrapling, and Playwright through `PROXY_URL`. |
| `PROXY_URL` | empty | Proxy URL, for example `http://user:pass@proxy.example:80/`. Supports `http`, `https`, `socks5`, and `socks5h`. |
| `STORAGE_SAVE_DEFAULT` | `off` | Persist all fetches by default. A per-request `persist` value or `Prefer: persist` still wins. |
| `STORAGE_DB_PATH` | `data/research.db` | SQLite database path. Docker Compose uses `/data/research.db`. |
| `STORAGE_USER_DICT_PATH` | `dictionaries/custom.txt` | Optional jieba user dictionary loaded at startup when non-empty. |
| `FETCH_ROUTE_TTL_HOURS` | `168` | Cache a successful hostname + target-kind route for seven days. |
| `API_AUTH_ENABLED` | `off` | Require Bearer authentication for all `/api/*` endpoints. |
| `API_ADMIN_KEY` | empty | Environment-only administrator token. Required when auth is enabled; at least 32 characters. |
| `API_KEY_PEPPER` | empty | Server-side pepper for client-key HMACs. Required when auth is enabled; at least 32 characters. |
| `API_DOCS_ENABLED` | `true` | Serve interactive OpenAPI docs at `/docs` and `/redoc`. |
| `WEB_CORS_ORIGINS` | `http://localhost:8080,http://127.0.0.1:8080` | Comma-separated allowed browser origins for the API. |

Invalid values fail fast at startup. For example, `PROXY_ENABLED=on` without
`PROXY_URL`, or authentication with short secrets, raises a configuration
error before the service accepts traffic.

## Fetch and discovery limits

`FETCHER_MAX_RESPONSE_BYTES` applies to every strategy. `FETCHER_ENFORCE_ROBOTS`
is checked before fetching a page; robots and sitemap discovery always use the
same user agent.

Timeout is a per-request value:

```json
{"url": "https://example.com/", "timeout_seconds": 90}
```

`timeout_seconds` is shared across failback stages, not per strategy.

## Persistence

Fetching is non-persistent by default. Choose persistence with, in priority
order:

1. `?persist=true` or `?persist=false`
2. `Prefer: persist`
3. `STORAGE_SAVE_DEFAULT=on`

Content is de-duplicated by SHA-256. Repeated content reuses the existing
document while recording another fetch-history row. The database uses SQLite
WAL mode, `synchronous=NORMAL`, foreign keys, and a 5-second busy timeout.

Docker Compose bind-mounts `./data:/data`, so a normal container stop, restart,
or Compose teardown does not remove the database. Back up `data/research.db`
(and its WAL files) when you need a portable copy.

To add domain-specific jieba words, put one word per line in
`dictionaries/custom.txt`. Docker mounts it read-only at
`/dictionaries/custom.txt`; the file is loaded at startup when non-empty.

## Proxy

The environment is the baseline:

```dotenv
PROXY_ENABLED=on
PROXY_URL=http://USERNAME:PASSWORD@p.webshare.io:80/
```

`PROXY_URL` is passed to HTTPX, curl-cffi, Scrapling, and Playwright. It is
never returned by the API or written to logs; logs redact the username and
password. macOS `127.0.0.1` proxies are not automatically reachable inside
Colima containers.

The Web UI can save a proxy override without restarting the service. Overrides
are stored in SQLite and apply immediately to page, robots, and sitemap
requests:

- **Clear proxy** saves an explicit direct-connection override.
- **Use environment** removes the override and restores the `.env` baseline.

With API authentication enabled, proxy settings require the administrator key.
See the proxy settings endpoints in the
[API Reference](api-reference.md#proxy-settings).

To verify that traffic exits through the proxy, fetch an IP echo endpoint and
inspect `meta.proxy_enabled`:

```sh
curl -sS -X POST 'http://127.0.0.1:7890/api/fetch' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://ipv4.webshare.io/","strategy":"httpx"}' \
  | jq '{code, proxy_enabled: .meta.proxy_enabled, ip: .data}'
```

## Authentication

Enable authentication whenever the service is reachable beyond localhost:

```dotenv
API_AUTH_ENABLED=on
API_ADMIN_KEY=<at-least-32-random-characters>
API_KEY_PEPPER=<different-at-least-32-random-secret>
```

When enabled, every `/api/*` endpoint requires
`Authorization: Bearer <token>`. Health probes remain anonymous.
`API_ADMIN_KEY` exists only in the environment. Client keys created through
`POST /api/keys` are shown once and stored in SQLite only as HMACs.

Treat a client token like a password: it cannot be recovered after the create
response. Do not put keys in query strings or commit them to `.env`.

## CORS and API docs

`WEB_CORS_ORIGINS` controls browser access to the API. The bundled Web UI is
served from the same origin as the API, so it does not need a CORS entry.
Set `API_DOCS_ENABLED=false` to disable `/docs` and `/redoc` in a hardened
deployment.

## Related documentation

- [API Reference](api-reference.md)
- [Deployment](deployment.md)
- [Failback and observability](failback.md)
