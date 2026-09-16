from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from trafilatura.metadata import extract_metadata


MAX_META_TAGS = 200
MAX_JSON_LD_BLOCKS = 20


def _append_value(values: dict[str, Any], key: str, value: str) -> None:
    """Preserve repeated HTML meta tags without forcing every field into a list."""
    existing = values.get(key)
    if existing is None:
        values[key] = value
    elif isinstance(existing, list):
        existing.append(value)
    else:
        values[key] = [existing, value]


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _trafilatura_metadata(html: str, url: str) -> dict[str, Any]:
    document = extract_metadata(html, default_url=url)
    fields = document.as_dict()
    allowed = {
        "title",
        "author",
        "url",
        "hostname",
        "description",
        "sitename",
        "date",
        "categories",
        "tags",
        "fingerprint",
        "id",
        "license",
        "language",
        "image",
        "pagetype",
    }
    return {key: fields.get(key) for key in allowed}


def extract_page_metadata(html: str, url: str) -> dict[str, Any]:
    """Combine raw SEO markup and Trafilatura's semantic metadata safely."""
    soup = BeautifulSoup(html, "html.parser")
    seo: dict[str, Any] = {}
    open_graph: dict[str, Any] = {}
    twitter: dict[str, Any] = {}
    raw_meta: list[dict[str, str]] = []

    for meta in soup.find_all("meta")[:MAX_META_TAGS]:
        content = _clean(meta.get("content"))
        if content is None:
            continue
        attribute = next((name for name in ("name", "property", "http-equiv", "itemprop") if meta.get(name)), None)
        if attribute is None:
            continue
        key = str(meta[attribute]).strip().lower()
        raw_meta.append({"attribute": attribute, "key": key, "content": content})
        if key in {"description", "keywords", "author", "robots"}:
            _append_value(seo, key, content)
        elif key.startswith("og:"):
            _append_value(open_graph, key.removeprefix("og:"), content)
        elif key.startswith("twitter:"):
            _append_value(twitter, key.removeprefix("twitter:"), content)

    canonical: str | None = None
    hreflang: list[dict[str, str]] = []
    for link in soup.find_all("link"):
        href = _clean(link.get("href"))
        if not href:
            continue
        rel = {str(item).lower() for item in link.get("rel", [])}
        resolved = urljoin(url, href)
        if "canonical" in rel and canonical is None:
            canonical = resolved
        if "alternate" in rel and link.get("hreflang"):
            hreflang.append({"language": str(link["hreflang"]), "url": resolved})

    json_ld: list[Any] = []
    json_ld_parse_errors = 0
    for script in soup.find_all("script", attrs={"type": lambda value: value and value.lower() == "application/ld+json"}):
        if len(json_ld) >= MAX_JSON_LD_BLOCKS:
            break
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            json_ld.append(json.loads(raw))
        except json.JSONDecodeError:
            json_ld_parse_errors += 1

    html_metadata = {
        "title": _clean(soup.title.get_text() if soup.title else None),
        "language": _clean(soup.html.get("lang") if soup.html else None),
        "seo": seo,
        "open_graph": open_graph,
        "twitter": twitter,
        "canonical": canonical,
        "hreflang": hreflang,
        "meta_tags": raw_meta,
        "meta_tags_truncated": len(soup.find_all("meta")) > MAX_META_TAGS,
        "json_ld": json_ld,
        "json_ld_truncated": len(json_ld) >= MAX_JSON_LD_BLOCKS,
        "json_ld_parse_errors": json_ld_parse_errors,
    }
    try:
        semantic = _trafilatura_metadata(html, url)
        semantic_error = None
    except Exception as exc:  # Metadata enrichment must not fail a usable page.
        semantic = {}
        semantic_error = f"{exc.__class__.__name__}: {str(exc)[:180]}"
    return {"html": html_metadata, "trafilatura": semantic, "trafilatura_error": semantic_error}
