# Web UI Design

## Scope

Add a lightweight frontend-only admin/temporary-user UI for the existing
FastAPI service. The frontend lives in `web/` and uses Alpine.js, daisyUI 5,
Lucide icons, and browser `fetch`; it does not introduce a frontend build
framework.

## Information architecture

The shell uses a navbar and a single content column. Each page follows:

```text
title → breadcrumb → small description → filter form → table → pagination
```

Navigation has two destinations: Dataset and Keys. The selected visual direction
is Reader library with a table-first layout: dense, scannable rows and a detail
dialog for full document content.

## API client and authentication

`web/api-client.js` is the only module allowed to call the backend. It stores a
user-entered Bearer token in localStorage, adds it to `/api/*` requests, parses
the common response envelope, and surfaces 401/403/errors consistently. Health
probes remain unauthenticated.

The UI prompts for a key when required. API key plaintext is only available at
creation; the Keys table masks it as the first four and last four characters.
The browser keeps a newly created token by key id in localStorage so Copy works
later in that browser. A token created elsewhere cannot be recovered from the
HMAC-only database and therefore has Copy disabled.

## Dataset page

The table uses `GET /api/documents` for paginated listing and `POST /api/search`
for keyword/filter searches. Filters cover title, sitename, tags, content,
hostname, and publication date. Rows show truncated title (20 characters),
site, publication time, fetch time, and actions. A detail dialog displays full
content and `meta.page`; delete requires confirmation and calls the document
delete endpoint.

## Keys page

The table shows key name, masked token, scopes, created/expiry time, and status.
The New dialog collects a name and scopes, calls `POST /api/keys`, stores the
one-time token locally, and displays it once with Copy. Copy uses the Clipboard
API with a visible fallback/error. Revoke uses a confirmation dialog and
`DELETE /api/keys/{id}`.

## Backend additions

Add document list/detail/delete endpoints without changing existing fetch,
search, or key contracts. List responses remain envelope-shaped and include
pagination metadata. API authentication protects all `/api/*` routes; the UI
does not bypass scopes or expose the environment admin key.

## Verification

Serve `web/` through the lightweight static server in Docker Compose, configure
the API base URL via an injected setting, and verify Dataset/Keys navigation,
auth persistence, pagination, search, create/copy/delete, error states, and
responsive layout in a browser. Run backend tests and an automated browser
smoke check before release.
