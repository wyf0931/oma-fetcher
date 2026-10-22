# Contributing

Thanks for taking the time to improve OMA Fetcher. This project favors small,
focused changes that keep the API envelope and failback behavior predictable.

## Development setup

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), and `jq`/`curl`
for manual API checks.

```sh
git clone https://github.com/wyf0931/oma-fetcher.git
cd oma-fetcher
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 7890
```

Or run the managed local instance:

```sh
bin/ops.sh start
bin/ops.sh status
bin/ops.sh stop
```

The Web UI is served at `http://127.0.0.1:7890/`; OpenAPI docs are at `/docs`.

## Tests

```sh
uv run pytest -q
```

Tests use FastAPI's test client and do not require a running container or
network access. Add or update tests for behavior changes. A change that affects
fetching, discovery, storage, authentication, or health probes should include a
regression test.

## Project layout

```text
app/
  main.py       FastAPI routes, middleware, envelope helpers
  models.py     Pydantic request/response models
  config.py     Environment-based settings
  fetchers.py   HTTP → browser escalation
  quality.py    Content assessment and article-card extraction
  discovery.py  robots.txt and sitemap discovery
  storage.py    SQLite document store, FTS5, keys, settings
  auth.py       Bearer authentication and scopes
  safety.py     URL and private-network checks
  metadata.py   Trafilatura metadata extraction
web/            Static Reader library UI (no build step)
docs/           Configuration, deployment, API, failback docs
tests/          Pytest suite
scripts/        Deployment helpers
bin/ops.sh      Local process manager
```

## Documentation changes

- `README.md` is the default English landing page.
- `README.zh-CN.md` is the Chinese translation. Keep both in sync.
- Detailed material belongs in `docs/`, not in the README.
- Keep code examples copy-pasteable and verify links and anchors.

## Pull request checklist

- [ ] `uv run pytest -q` passes.
- [ ] New behavior has tests.
- [ ] `README.md` and `README.zh-CN.md` are updated when user-facing behavior changes.
- [ ] Relevant docs in `docs/` are updated.
- [ ] No secrets, `.env` files, databases, or tokens are committed.
- [ ] The change is focused; unrelated refactors are separate PRs.

## Commit messages

Use conventional, scoped subjects such as:

```text
feat(fetch): honor Prefer: persist
fix(discovery): accept empty robots 404
docs: restructure README
chore(deps): update trafilatura
```

## Security

Do not open a public issue for a vulnerability. Report it privately to the
maintainer listed in the repository profile, and include reproduction steps
without real credentials. Proxy credentials, API keys, and client tokens must
never appear in logs, screenshots, or fixtures.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
