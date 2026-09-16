from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit, urlunsplit


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
    storage_path: str = field(default_factory=lambda: os.getenv("STORAGE_DB_PATH", "data/research.db"))
    storage_save_default: bool = field(default_factory=lambda: _as_bool("STORAGE_SAVE_DEFAULT", False))
    storage_user_dict_path: str = field(default_factory=lambda: os.getenv("STORAGE_USER_DICT_PATH", "dictionaries/custom.txt"))
    fetch_route_ttl_hours: int = field(default_factory=lambda: int(os.getenv("FETCH_ROUTE_TTL_HOURS", "168")))
    api_auth_enabled: bool = field(default_factory=lambda: _as_bool("API_AUTH_ENABLED", False))
    api_admin_key: str = field(default_factory=lambda: os.getenv("API_ADMIN_KEY", "").strip())
    api_key_pepper: str = field(default_factory=lambda: os.getenv("API_KEY_PEPPER", "").strip())
    api_docs_enabled: bool = field(default_factory=lambda: _as_bool("API_DOCS_ENABLED", True))
    web_cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(item.strip() for item in os.getenv("WEB_CORS_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(",") if item.strip()))
    proxy_enabled: bool = field(default_factory=lambda: _as_bool("PROXY_ENABLED", False))
    proxy_url: str = field(default_factory=lambda: os.getenv("PROXY_URL", "").strip())

    def __post_init__(self) -> None:
        if self.proxy_enabled and not self.proxy_url:
            raise ValueError("PROXY_URL must be set when PROXY_ENABLED=on")
        if self.proxy_url and urlsplit(self.proxy_url).scheme not in {"http", "https", "socks5", "socks5h"}:
            raise ValueError("PROXY_URL must use http(s) or socks5(s) scheme")
        if self.api_auth_enabled and (len(self.api_admin_key) < 32 or len(self.api_key_pepper) < 32):
            raise ValueError("API_ADMIN_KEY and API_KEY_PEPPER must each be at least 32 characters when API_AUTH_ENABLED=on")

    @property
    def active_proxy_url(self) -> str | None:
        return self.proxy_url if self.proxy_enabled else None

    @property
    def proxy_mapping(self) -> dict[str, str] | None:
        if not self.active_proxy_url:
            return None
        return {"http": self.active_proxy_url, "https": self.active_proxy_url}

    @property
    def browser_proxy(self) -> dict[str, str] | None:
        if not self.active_proxy_url:
            return None
        parsed = urlsplit(self.active_proxy_url)
        proxy = {"server": urlunsplit((parsed.scheme, parsed.netloc.split("@")[-1], "", "", ""))}
        if parsed.username:
            proxy["username"] = unquote(parsed.username)
        if parsed.password:
            proxy["password"] = unquote(parsed.password)
        return proxy

    @property
    def proxy_label(self) -> str | None:
        if not self.active_proxy_url:
            return None
        parsed = urlsplit(self.active_proxy_url)
        return urlunsplit((parsed.scheme, parsed.netloc.split("@")[-1], "", "", ""))

    def redact(self, value: str) -> str:
        if self.proxy_url:
            return value.replace(self.proxy_url, self.proxy_label or "[proxy]")
        return value


settings = Settings()
