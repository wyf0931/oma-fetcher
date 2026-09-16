from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    allow_private_networks: bool = _as_bool("FETCHER_ALLOW_PRIVATE_NETWORKS", False)
    enforce_robots: bool = _as_bool("FETCHER_ENFORCE_ROBOTS", True)
    max_response_bytes: int = int(os.getenv("FETCHER_MAX_RESPONSE_BYTES", "5242880"))
    sitemap_max_urls: int = int(os.getenv("FETCHER_SITEMAP_MAX_URLS", "10000"))
    sitemap_max_depth: int = int(os.getenv("FETCHER_SITEMAP_MAX_DEPTH", "4"))
    discovery_retries: int = int(os.getenv("FETCHER_DISCOVERY_RETRIES", "2"))
    discovery_retry_delay: float = float(os.getenv("FETCHER_DISCOVERY_RETRY_DELAY", "0.4"))
    user_agent: str = os.getenv("FETCHER_USER_AGENT", "oma-fetcher/0.1")


settings = Settings()
