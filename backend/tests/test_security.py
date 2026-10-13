from __future__ import annotations

import socket

import pytest

from app.security import UnsafeTargetError, validate_public_url, validate_webhook_url


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1:8000/",
        "http://10.1.2.3/",
        "http://192.168.0.10/",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "https://user:secret@example.com/",
        "http://service.internal/",
        "http://dev.local/",
    ],
)
def test_blocks_local_and_unsafe_targets(url: str) -> None:
    with pytest.raises(UnsafeTargetError):
        validate_public_url(url)


def test_public_literal_ip_is_accepted_without_dns() -> None:
    assert validate_public_url("https://8.8.8.8/status", resolve_dns=True) == "https://8.8.8.8/status"


def test_hostname_that_resolves_to_private_address_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeTargetError, match="private or restricted"):
        validate_public_url("https://looks-public.example/page")


def test_hostname_that_resolves_to_public_address_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert validate_public_url("https://docs.example.com/path").endswith("/path")


def test_webhook_allowlist() -> None:
    assert validate_webhook_url("https://discord.com/api/webhooks/123/secret")
    assert validate_webhook_url("https://api.telegram.org/bot123/sendMessage?chat_id=4")
    with pytest.raises(UnsafeTargetError):
        validate_webhook_url("https://attacker.example/callback")
    with pytest.raises(UnsafeTargetError):
        validate_webhook_url("http://discord.com/api/webhooks/123/secret")
    with pytest.raises(UnsafeTargetError, match="sendMessage"):
        validate_webhook_url("https://api.telegram.org/bot123/getMe")
