from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit


class UnsafeUrlError(ValueError):
    pass


def safe_redirect_target(current_url: str, location: str, *, allow_private: bool) -> str:
    target = urljoin(current_url, location)
    validate_public_url(target, allow_private=allow_private)
    return target


def validate_public_url(url: str, *, allow_private: bool) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError("only absolute http(s) URLs are allowed")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URLs with embedded credentials are not allowed")
    if allow_private:
        return
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as exc:
        raise UnsafeUrlError("hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeUrlError("private or non-routable network targets are not allowed")
