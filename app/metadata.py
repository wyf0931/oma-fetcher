from __future__ import annotations

from typing import Any

from trafilatura.metadata import extract_metadata


METADATA_FIELDS = (
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
)


def extract_page_metadata(html: str, url: str) -> dict[str, Any]:
    """Return Trafilatura's semantic page metadata without extraction internals."""
    document = extract_metadata(html, default_url=url)
    fields = document.as_dict()
    return {key: fields.get(key) for key in METADATA_FIELDS}
