from __future__ import annotations

import ipaddress
import socket
from urllib.parse import parse_qs, urlparse


class UnsafeTargetError(ValueError):
    """Raised when a URL could reach a local, reserved, or otherwise unsafe host."""


_DENIED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.goog",
    "instance-data.ec2.internal",
}


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


def validate_public_url(url: str, *, resolve_dns: bool = True) -> str:
    """Validate an HTTP(S) URL and reject private/local destinations.

    DNS results are checked before a browser navigates, and the browser request route
    re-checks every subresource and redirect. This is defense in depth, not a promise
    against every possible DNS-rebinding race in arbitrary browser environments.
    """
    if not isinstance(url, str) or not url.strip():
        raise UnsafeTargetError("Enter a valid public HTTP or HTTPS URL.")
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeTargetError("Only public HTTP and HTTPS pages can be monitored.")
    if not parsed.hostname:
        raise UnsafeTargetError("The URL must include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeTargetError("URLs containing usernames or passwords are not allowed.")
    host = parsed.hostname.rstrip(".").lower()
    if host in _DENIED_HOSTS or host.endswith((".localhost", ".local", ".internal")):
        raise UnsafeTargetError("Local and internal hostnames cannot be monitored.")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        is_ip = False
    if is_ip:
        if not _is_public_ip(host):
            raise UnsafeTargetError("Private, loopback, link-local, and reserved IPs are blocked.")
        return url.strip()
    if not resolve_dns:
        return url.strip()
    try:
        answers = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeTargetError("The hostname could not be resolved. Check the URL and try again.") from exc
    addresses = {item[4][0].split("%", 1)[0] for item in answers}
    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise UnsafeTargetError("This hostname resolves to a private or restricted network address.")
    return url.strip()


def validate_webhook_url(url: str | None) -> str | None:
    """Allow only common HTTPS webhook destinations; do not accept arbitrary callbacks."""
    if url is None or not url.strip():
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise UnsafeTargetError("Notification webhooks must use HTTPS.")
    host = parsed.hostname.lower().rstrip(".")
    if host not in {"discord.com", "discordapp.com", "api.telegram.org"}:
        raise UnsafeTargetError("Use a Discord webhook URL or a Telegram bot API URL.")
    if host in {"discord.com", "discordapp.com"} and not parsed.path.startswith("/api/webhooks/"):
        raise UnsafeTargetError("A Discord URL must be a Discord webhook endpoint.")
    if host == "api.telegram.org" and (not parsed.path.endswith("/sendMessage") or not parse_qs(parsed.query).get("chat_id")):
        raise UnsafeTargetError("A Telegram URL must be a sendMessage endpoint with chat_id configured.")
    if parsed.username or parsed.password:
        raise UnsafeTargetError("Webhook URLs must not contain embedded credentials.")
    return url.strip()
