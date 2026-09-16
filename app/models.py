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
    data: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

