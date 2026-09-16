from __future__ import annotations

from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, Field


OutputFormat = Literal["markdown", "txt", "json", "xml"]
Strategy = Literal["auto", "httpx", "curl_cffi", "scrapling", "playwright"]


class FetchRequest(BaseModel):
    url: AnyHttpUrl
    output_format: OutputFormat = "markdown"
    timeout_seconds: int = Field(default=45, ge=3, le=180)
    strategy: Strategy = "auto"


class ApiEnvelope(BaseModel):
    code: int
    message: str
    data: Any | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    hostname: str | None = Field(default=None, max_length=255)
    published_after: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    published_before: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    limit: int = Field(default=20, ge=1, le=100)
