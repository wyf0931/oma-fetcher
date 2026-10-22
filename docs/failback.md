# Failback and observability

OMA Fetcher treats HTTP success and content success as different things. A page
can return `200` and still be a WAF challenge, a cookie notice, a browser
support message, or an empty SPA shell. The fetcher escalates until it obtains
usable content or exhausts the configured timeout.

## Fetch pipeline

```text
httpx → curl-cffi → Scrapling stealth → Playwright
              ↓
      content assessment
              ↓
   Trafilatura / article cards
```

`/api/fetch` first tries lighter HTTP strategies. If the response has no
meaningful main content, it escalates to a stealth browser and finally to
Playwright. The same timeout budget is shared across stages.

Discovery endpoints (`/api/robots`, `/api/sitemap`) use:

```text
httpx → curl-cffi → Scrapling HTTP → Scrapling stealth browser
```

The discovery chain then retries as a whole with bounded jitter. The browser
stage is launched only when lighter strategies cannot return an actual robots
or sitemap document, such as IEC's empty HTTP `202` placeholder response.

## Smart content assessment

The assessor distinguishes:

- article text
- rendered listing cards
- robots directives
- sitemap XML
- cookie/browser fallback text
- empty `202` responses
- anti-bot placeholders

For example, an ITU news-listing page whose Trafilatura output is a browser
support message is rendered as a Markdown card list instead of being stored as
that message.

`meta.content_kind` is `article` or `listing`.
`meta.extraction_method` identifies `trafilatura` or `article_cards`.

## Route cache

Successful routes are cached in SQLite by normalized hostname and target kind
(`page`, `robots`, or `sitemap`) for seven days by default. The next request
starts with the most recently successful strategy. If it fails, the cache entry
is expired and the complete failback chain resumes.

Configure the route TTL:

```dotenv
FETCH_ROUTE_TTL_HOURS=168
```

Route caching requires the SQLite Document Store to be available. When storage
is unavailable, every request starts from the full chain.

## Observability

`meta.failback` provides non-sensitive diagnostics:

```json
{
  "route_hit": true,
  "preferred_strategy": "httpx",
  "accepted_strategy": "httpx",
  "signals": ["rendered_article_cards"]
}
```

Each result also exposes the full attempt trace:

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
HTTP status, and errors. Proxy credentials are redacted.

## Troubleshooting `data: null`

`code: 0` is the success criterion. A printed `null` from `jq -r '.data'` means
the API returned an error envelope with no data. Inspect the whole envelope
instead of treating `null` as content:

```sh
curl -sS --get 'http://127.0.0.1:7890/api/robots' \
  --data-urlencode 'url=https://www.iso.org/' \
  | jq '{code, message, attempts: .meta.attempts}'
```

| Symptom | Likely cause | Next step |
| --- | --- | --- |
| HTTP `403`, `code: 2001` | `robots.txt` disallows the URL. | Check `/api/robots`; do not bypass unless authorized. |
| `code: 2002` | Page fetched but no extractable main content. | Inspect `meta.attempts`, `meta.content_kind`, and `meta.failback.signals`. |
| `code: 2003` | All fetch strategies failed within the timeout. | Increase `timeout_seconds`, check egress/proxy, inspect `meta.attempts`. |
| Empty or shell-only content | SPA or anti-bot placeholder. | Retry with a longer timeout so Playwright can render; check listing assessment. |
| `code: 1002` | Unsafe URL rejected. | Use a public HTTP(S) URL or enable private networks only in a trusted deployment. |
| `code: 4003` / HTTP `503` | SQLite store not ready. | Check `/readyz`, `data/` permissions, and logs. |

## Related documentation

- [Configuration](configuration.md)
- [API Reference](api-reference.md)
- [Deployment](deployment.md)
