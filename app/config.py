from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit, urlunsplit


def _as_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    allow_private_networks: bool = _as_bool("FETCHER_ALLOW_PRIVATE_NETWORKS", False)
    enforce_robots: bool = _as_bool("FETCHER_ENFORCE_ROBOTS", True)
    max_response_bytes: int = int(os.getenv("FETCHER_MAX_RESPONSE_BYTES", "5242880"))
    sitemap_max_urls: int = int(os.getenv("FETCHER_SITEMAP_MAX_URLS", "10000"))
    sitemap_max_depth: int = int(os.getenv("FETCHER_SITEMAP_MAX_DEPTH", "4"))
    discovery_retries: int = int(os.getenv("FETCHER_DISCOVERY_RETRIES", "2"))
    discovery_retry_delay: float = float(os.getenv("FETCHER_DISCOVERY_RETRY_DELAY", "0.4"))
    user_agent: str = os.getenv("FETCHER_USER_AGENT", "oma-fetcher/1.5")
    storage_path: str = field(default_factory=lambda: os.getenv("STORAGE_DB_PATH", "data/research.db"))
    storage_save_default: bool = field(default_factory=lambda: _as_bool("STORAGE_SAVE_DEFAULT", False))
    storage_user_dict_path: str = field(default_factory=lambda: os.getenv("STORAGE_USER_DICT_PATH", "dictionaries/custom.txt"))
    fetch_route_ttl_hours: int = field(default_factory=lambda: int(os.getenv("FETCH_ROUTE_TTL_HOURS", "168")))
    api_auth_enabled: bool = field(default_factory=lambda: _as_bool("API_AUTH_ENABLED", False))
    api_key_pepper: str = field(default_factory=lambda: os.getenv("API_KEY_PEPPER", "").strip())
    session_ttl_hours: int = field(default_factory=lambda: int(os.getenv("SESSION_TTL_HOURS", "168")))
    session_cookie_name: str = field(default_factory=lambda: os.getenv("SESSION_COOKIE_NAME", "oma_session").strip() or "oma_session")
    bootstrap_admin_email: str = field(default_factory=lambda: os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower())
    bootstrap_admin_password: str = field(default_factory=lambda: os.getenv("BOOTSTRAP_ADMIN_PASSWORD", ""))
    debug: bool = field(default_factory=lambda: _as_bool("DEBUG", False))
    api_docs_enabled: bool = field(default_factory=lambda: _as_bool("API_DOCS_ENABLED", True))
    web_cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(item.strip() for item in os.getenv("WEB_CORS_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(",") if item.strip()))
    proxy_enabled: bool = field(default_factory=lambda: _as_bool("PROXY_ENABLED", False))
    proxy_url: str = field(default_factory=lambda: os.getenv("PROXY_URL", "").strip())
    proxy_override: bool = False
    proxy_environment_enabled: bool = field(init=False)
    proxy_environment_url: str = field(init=False)
    # Alipay Vibe Pay (web page.pay). Billing routes only activate when an app_id
    # and both RSA2 keys are present, so dev/UAT without credentials is unaffected.
    alipay_app_id: str = field(default_factory=lambda: os.getenv("ALIPAY_APP_ID", "").strip())
    alipay_gateway: str = field(default_factory=lambda: os.getenv("ALIPAY_GATEWAY", "https://openapi.alipay.com/gateway.do").strip())
    alipay_merchant_private_key: str = field(default_factory=lambda: os.getenv("ALIPAY_MERCHANT_PRIVATE_KEY", "").strip())
    alipay_alipay_public_key: str = field(default_factory=lambda: os.getenv("ALIPAY_ALIPAY_PUBLIC_KEY", "").strip())
    alipay_notify_url: str = field(default_factory=lambda: os.getenv("ALIPAY_NOTIFY_URL", "").strip())
    alipay_return_url: str = field(default_factory=lambda: os.getenv("ALIPAY_RETURN_URL", "").strip())

    def __post_init__(self) -> None:
        self.proxy_environment_enabled = self.proxy_enabled
        self.proxy_environment_url = self.proxy_url
        if self.proxy_enabled and not self.proxy_url:
            raise ValueError("PROXY_URL must be set when PROXY_ENABLED=on")
        if self.proxy_url and urlsplit(self.proxy_url).scheme not in {"http", "https", "socks5", "socks5h"}:
            raise ValueError("PROXY_URL must use http(s) or socks5(s) scheme")
        if self.api_auth_enabled and len(self.api_key_pepper) < 32:
            raise ValueError("API_KEY_PEPPER must be at least 32 characters when API_AUTH_ENABLED=on")
        if self.session_ttl_hours < 1:
            raise ValueError("SESSION_TTL_HOURS must be at least 1")
        if self.alipay_app_id and not (self.alipay_merchant_private_key and self.alipay_alipay_public_key):
            raise ValueError("ALIPAY_MERCHANT_PRIVATE_KEY and ALIPAY_ALIPAY_PUBLIC_KEY are required when ALIPAY_APP_ID is set")

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
            value = value.replace(self.proxy_url, self.proxy_label or "[proxy]")
        return re.sub(r"(?i)(https?|socks5h?)://[^\s/@:]+(?::[^\s/@]*)?@", r"\1://[redacted]@", value)

    def apply_proxy_override(self, value: dict | None) -> None:
        self.proxy_override = value is not None
        if value is None:
            self.proxy_enabled = self.proxy_environment_enabled
            self.proxy_url = self.proxy_environment_url
            return
        self.proxy_enabled = bool(value.get("enabled"))
        self.proxy_url = str(value.get("url") or "")

    @property
    def alipay_enabled(self) -> bool:
        """True when Alipay credentials are configured well enough to sell credits."""
        return bool(self.alipay_app_id and self.alipay_merchant_private_key and self.alipay_alipay_public_key)


settings = Settings()
