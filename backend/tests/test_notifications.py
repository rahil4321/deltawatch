from __future__ import annotations

from app import config
from app.notifications import send_email_notification


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def ehlo(self):
        return None

    def starttls(self, context=None):
        return None

    def login(self, username, password):
        return None

    def send_message(self, message):
        self.sent.append(message)


def test_email_alert_reports_missing_smtp_configuration(monkeypatch) -> None:
    monkeypatch.setattr(config, "SMTP_HOST", "")
    monkeypatch.setattr(config, "SMTP_FROM", "")
    ok, message = send_email_notification(
        "reviewer@example.com", title="Deadline", summary="The deadline changed",
        page_url="https://example.com", change_url="http://localhost:5173/?event=1",
    )
    assert not ok
    assert "not configured" in message


def test_email_alert_uses_configured_smtp(monkeypatch) -> None:
    FakeSMTP.sent.clear()
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    monkeypatch.setattr(config, "SMTP_USERNAME", "bot@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "test-password")
    monkeypatch.setattr(config, "SMTP_FROM", "bot@example.com")
    monkeypatch.setattr(config, "SMTP_USE_TLS", True)
    monkeypatch.setattr("app.notifications.smtplib.SMTP", FakeSMTP)
    ok, message = send_email_notification(
        "reviewer@example.com", title="Deadline", summary="The deadline moved",
        page_url="https://example.com/scholarship", change_url="http://localhost:5173/?event=7",
    )
    assert ok and message == "sent"
    assert len(FakeSMTP.sent) == 1
    assert FakeSMTP.sent[0]["To"] == "reviewer@example.com"
    assert "The deadline moved" in FakeSMTP.sent[0].get_content()
