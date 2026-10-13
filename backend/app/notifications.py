from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from email.message import EmailMessage
import smtplib
import ssl

import requests

from . import config

from .security import validate_webhook_url


def send_notification(webhook_url: str, *, title: str, summary: str, page_url: str, change_url: str) -> tuple[bool, str]:
    """Send a concise Discord or preconfigured Telegram message with a short timeout."""
    try:
        safe_url = validate_webhook_url(webhook_url)
        assert safe_url
        host = urlparse(safe_url).hostname or ""
        message = f"**DeltaWatch · {title[:180]}**\n{summary[:700]}\n{page_url}\n{change_url}"
        if host in {"discord.com", "discordapp.com"}:
            response = requests.post(safe_url, json={"content": message[:1900]}, timeout=(3, 6))
        else:
            message = message.replace("**", "")
            parsed = urlparse(safe_url)
            query = parse_qs(parsed.query)
            if not parsed.path.endswith("/sendMessage") or not query.get("chat_id"):
                return False, "Telegram URL must be a sendMessage endpoint with chat_id configured."
            response = requests.post(
                safe_url,
                json={"text": f"DeltaWatch · {title[:180]}\n{summary[:700]}\n{page_url}\n{change_url}"},
                timeout=(3, 6),
            )
        if 200 <= response.status_code < 300:
            return True, "sent"
        return False, f"Webhook returned HTTP {response.status_code}."
    except Exception as exc:  # Notification failures must not fail a capture job.
        return False, f"Notification failed: {str(exc)[:180]}"


def send_email_notification(recipient: str, *, title: str, summary: str, page_url: str, change_url: str) -> tuple[bool, str]:
    """Send an email if SMTP is configured; never let alert delivery break monitoring."""
    if not config.SMTP_HOST or not config.SMTP_FROM:
        return False, "Email alerts are not configured on this backend. Set DELTAWATCH_SMTP_HOST and DELTAWATCH_SMTP_FROM."
    try:
        message = EmailMessage()
        message["Subject"] = f"DeltaWatch change detected: {title[:120]}"
        message["From"] = config.SMTP_FROM
        message["To"] = recipient
        message.set_content(
            f"DeltaWatch detected a meaningful website change.\n\n"
            f"Page: {page_url}\n\nSummary: {summary}\n\n"
            f"View evidence: {change_url}\n\n"
            "This alert was generated from the captured text comparison. Review the before/after evidence before acting."
        )
        context = ssl.create_default_context()
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=8) as server:
            server.ehlo()
            if config.SMTP_USE_TLS:
                server.starttls(context=context)
                server.ehlo()
            if config.SMTP_USERNAME:
                server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.send_message(message)
        return True, "sent"
    except Exception as exc:
        return False, f"Email delivery failed: {str(exc)[:180]}"
