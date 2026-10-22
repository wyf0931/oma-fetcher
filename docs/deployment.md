# Deployment

OMA Fetcher is a single FastAPI service. The same process serves the API, the
optional Reader library Web UI, and the OpenAPI docs. The published container
image contains Chromium, Playwright, and Scrapling dependencies.

Published image:

```text
ghcr.io/wyf0931/oma-fetcher
```

## Requirements

- Docker with Compose v2 (Docker Desktop, Colima, or a Linux Docker host)
- 2 GiB of memory for the container; more for heavy Playwright workloads
- Outbound network access to the sites you fetch

For local Python development you also need [uv](https://docs.astral.sh/uv/)
and Python 3.12+.

## macOS one-command install

On a fresh macOS machine, the installer downloads the versioned script from
this repository. It installs Homebrew, Git, Docker CLI/Compose, and Colima only
when they are missing; starts Colima with a conservative 1 CPU / 2 GiB minimum;
and pulls the published GHCR image. It **does not build Docker images locally**.

```sh
curl -fsSL https://raw.githubusercontent.com/wyf0931/oma-fetcher/main/scripts/install-macos.sh | bash
```

The service and Web UI are available at `http://127.0.0.1:7890` (UI at `/`, API
docs at `/docs`). To inspect the script before running it:

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

## Docker Compose

```sh
cp .env.example .env
docker compose pull
docker compose up -d
docker compose ps
curl -sS http://127.0.0.1:7890/healthz | jq
```

Follow logs with:

```sh
docker compose logs -f fetcher
```

Stop the deployment with `docker compose down`. The SQLite database remains in
`./data` because Compose bind-mounts `./data:/data`.

To pin a version instead of `latest`:

```sh
FETCHER_IMAGE=ghcr.io/wyf0931/oma-fetcher:1.5.0 docker compose up -d
```

### Image tags

The publish workflow produces:

| Tag | Meaning |
| --- | --- |
| `latest` | Latest build from `main`. |
| `1.5.0` | Exact release version. |
| `1.5` | Latest patch of a minor release. |
| `1` | Latest minor release of a major version. |
| `sha-<commit>` | Immutable build for a commit. |
| `<branch>` | Latest build for a branch. |

## Upgrade and rollback

```sh
docker compose pull
docker compose up -d --force-recreate
```

Rollback by pinning the previous version:

```sh
FETCHER_IMAGE=ghcr.io/wyf0931/oma-fetcher:1.4.3 docker compose up -d --force-recreate
```

Database migrations are applied automatically at startup. Back up `data/`
before a major upgrade.

## Local Python development

```sh
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 7890
```

To manage the API and static Web UI together, use the project helper. It runs
`uvicorn` and Python's static server directly (no Docker), and stores PIDs and
logs in the system temporary directory:

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

The API and Web UI use the same default port, 7890. `bin/ops.sh` loads `.env`
when present, so local and Compose deployments share the same environment
baseline.

## Health probes

HTTP status is the primary signal: `200` is healthy/ready and `503` means not
ready.

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

Use `/livez` for container liveness and `/readyz` for load-balancer readiness.
The Compose healthcheck uses `/readyz`.

## Colima and proxy configuration

When the service needs a proxy, Docker Compose reads `PROXY_ENABLED` and
`PROXY_URL` from `.env`. The default is direct outbound traffic:

```sh
cp .env.example .env
# Edit .env only if a proxy is required.
PROXY_ENABLED=off
```

To force every fetch strategy through an authenticated proxy:

```dotenv
PROXY_ENABLED=on
PROXY_URL=http://USERNAME:PASSWORD@p.webshare.io:80/
```

Then restart the service:

```sh
docker compose pull
docker compose up -d --force-recreate
```

macOS `127.0.0.1` proxies are not automatically reachable inside Colima
containers. Use the host's reachable address or a proxy outside Colima.
See [Configuration](configuration.md#proxy) for the Web UI override and
credential handling.

## Web UI

Open `http://127.0.0.1:7890/` for the Reader library UI. It provides Dataset and
Keys pages, Bearer-key reuse, table filtering/pagination, document
details/delete, and key create/copy/delete.

Interactive OpenAPI documentation is available at `/docs` when
`API_DOCS_ENABLED=true` (the default).

## Security checklist

- Set `API_AUTH_ENABLED=on` for any deployment reachable beyond localhost.
- Keep `API_ADMIN_KEY` and `API_KEY_PEPPER` out of source control.
- Leave `FETCHER_ALLOW_PRIVATE_NETWORKS=false` unless the deployment must read
  private hosts.
- Keep `FETCHER_ENFORCE_ROBOTS=true` unless you have a specific, reviewed reason.
- Restrict network egress if the service is exposed to untrusted callers.
- Back up `data/` before upgrades and keep `.env` private.

## Related documentation

- [Configuration](configuration.md)
- [API Reference](api-reference.md)
- [Failback and observability](failback.md)
