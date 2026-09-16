# Fetcher Pipeline Design

## Scope

Build a single-URL FastAPI service. It exposes discovery separately from page
fetching and extraction; batch crawling, authentication, proxies, and content
storage are out of scope.

## API

All endpoints return a common envelope:

```json
{"code": 0, "message": "ok", "data": "...", "meta": {}}
```

`POST /api/fetch` accepts a URL plus `output_format` (`markdown`, `txt`,
`json`, or `xml`; Markdown is the default), a total timeout, and an optional
strategy override. Successful extraction places the requested Trafilatura
output in `data`. `meta` records the final URL, winning fetch strategy,
content type, and attempts. Failures use a nonzero code and contain
non-sensitive attempt diagnostics.

`GET /api/robots?url=` normalizes its input to the origin and returns the raw
`/robots.txt` body in `data`.

`GET /api/sitemap?url=` accepts an origin, ordinary page URL, or sitemap URL.
It returns a JSON-encoded, de-duplicated URL array in `data`; metadata records
the discovered sitemap documents, count, and truncation state.

## Architecture

Discovery and extraction are independent services.

```text
Discovery: URL -> robots.txt -> Sitemap declarations / standard sitemap paths
                         -> Trafilatura sitemap discovery -> URL set

Fetch: URL -> httpx -> curl-cffi -> Scrapling stealth -> Playwright Chromium
                                                         -> HTML
Extract: HTML -> Trafilatura -> requested output format
```

The fetch pipeline only escalates when an attempt has a retryable transport or
HTTP failure, a known anti-bot/interstitial response, or insufficient
extractable page content. Non-retryable client errors fail directly. Each stage
has an independent timeout within the request-wide deadline.

The first two stages are `httpx` and `curl-cffi`; the latter impersonates a
browser network stack. The third uses Scrapling's `StealthyFetcher`; the final
stage uses Playwright Chromium for pages requiring JavaScript. HTML never
crosses process boundaries unless a library requires it.

Sitemap discovery uses Trafilatura's sitemap utilities where available,
starting from Sitemap declarations in robots.txt and conventional sitemap
locations. It recursively expands sitemap indexes, deduplicates results, and
enforces configured depth and item limits. Scrapling's `SitemapSpider` remains
an extension point, not the mandatory primary path.

## Safety and operations

URLs are normalized and resolved before network access. Loopback, private,
link-local, multicast, and unspecified addresses are rejected by default to
avoid SSRF; an explicit configuration flag can relax this for trusted local
deployments. Redirect targets receive the same validation. Response bytes,
sitemap count, recursion depth, and timeouts are capped.

Robots are retrieved as a discovery artifact. Page-fetch policy is configurable
and defaults to enforcement: a disallowed URL returns a clear policy error.

Any browser profile, download, or transformed intermediate file uses a
per-request `tempfile.TemporaryDirectory` and is removed at completion. API
responses never include request cookies, proxy credentials, or raw exception
traces.

## Delivery

The project contains a Python 3.12 FastAPI application, typed Pydantic request
and response models, isolated fetcher and discovery modules, Dockerfile,
docker-compose configuration, environment example, and tests for escalation,
formats, robots, sitemap indexes, URL safety, and API response envelopes.
The Docker image installs httpx, curl-cffi, Scrapling, Trafilatura, Playwright,
and the Chromium runtime with its Linux dependencies.
