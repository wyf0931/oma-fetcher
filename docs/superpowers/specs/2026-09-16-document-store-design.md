# v1.2 Document Store Design

## Purpose

Add a local, durable document store to OMA Fetcher. Fetching remains usable
without persistence. When persistence is requested, the service stores the
extracted original content, page metadata, and fetch history, then makes it
searchable with SQLite FTS5 and jieba tokenization.

## API contract

`POST /api/fetch` retains its current response envelope. Persistence is
requested in this priority order:

1. Query parameter `persist=true|false`.
2. Request header `Prefer: persist`.
3. Environment setting `STORAGE_SAVE_DEFAULT=off|on`.

`persist=true` is mandatory: if the transaction cannot complete, the endpoint
returns a storage error rather than reporting a saved document. `Prefer:
persist` is a preference; a successful response includes `Preference-Applied:
persist`. Successful fetch metadata gains:

```json
{
  "storage": {
    "requested": true,
    "saved": true,
    "document_id": 42,
    "deduplicated": false
  }
}
```

`POST /api/search` accepts a query and optional hostname/date filters:

```json
{
  "query": "国家标准 外文版",
  "hostname": "samr.gov.cn",
  "published_after": "2026-01-01",
  "published_before": "2026-12-31",
  "limit": 20
}
```

It returns a JSON array in `data`. Each result includes document identity,
title, URL, hostname, publication date, BM25 score, and a tokenized FTS
snippet. The global API envelope remains unchanged for string-returning
endpoints.

## Data model

The database defaults to `data/research.db` for direct development and
`/data/research.db` in Docker. Each connection configures:

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

`documents` is the source of truth. It stores original content, request/final
URLs, canonical URL, flat page metadata, content SHA-256, full metadata JSON,
raw reader response, and timestamps. `content_hash` is unique.

The v1.1 reader input is `data` for extracted content and `meta.page` for
flat Trafilatura metadata. `meta.page.tags` can contain comma-separated values
inside an array (for example `["意见,国家标准,市场"]`). Ingestion splits common
Chinese and ASCII comma delimiters, trims whitespace, removes empty values,
deduplicates in order, then tokenizes the normalized tags for indexing.

`fetches` stores every successful persisted fetch, linked to the resulting
document. It records requested URL, final URL, strategy, status, content type,
attempt history, and fetch time. Repeated content creates a new fetch history
row but reuses the existing document.

`document_search` stores only jieba-tokenized title, description, tags, and
content. `documents_fts` is an external-content FTS5 table over this search
table. Insert/update/delete triggers keep it synchronized.

FTS BM25 weights are title 5, description 2, tags 3, and content 1. Tags are
normalized from page metadata, tokenized by jieba, and indexed independently.
The original document content is never replaced by tokenized text.

## Ingestion flow

```text
fetch + extract
  -> resolve persistence preference
  -> normalize metadata and SHA-256 original content
  -> jieba title/description/tags/content
  -> one SQLite transaction
       -> insert or reuse documents row by content_hash
       -> upsert document_search
       -> insert fetches row
       -> FTS triggers synchronize index
```

The store owns all SQL and transaction logic. The FastAPI handler only resolves
the request preference and passes a typed fetched-document record to the store.

## Search flow

The service tokenizes the query with jieba, constructs a safe prefix FTS query,
and combines it with parameterized hostname and inclusive publication-date
filters. Search never interpolates filters into SQL. The FTS result is ordered
by weighted BM25 and includes a snippet from the indexed content.

## Custom dictionaries and persistence

`dictionaries/custom.txt` is an empty, versioned file. If it contains entries,
jieba loads it during store initialization. A missing file is allowed.

Docker Compose bind-mounts `./data:/data` and
`./dictionaries:/dictionaries:ro`, so container replacement, stop, and normal
Compose teardown do not discard the database or custom dictionary. `data/` is
ignored by Git.

## Error handling and tests

Storage is optional by default. A fetch without persistence must succeed even
when the database is unavailable. Explicit persistence errors are reported
clearly and never claim a document was saved.

Tests cover PRAGMA/schema creation, content deduplication plus fetch history,
custom dictionary loading, FTS title/tag/content matching, filters, snippets,
preference priority, and API envelopes. Docker Compose configuration is
validated for both database and dictionary mounts.
