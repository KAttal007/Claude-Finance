"""Alerts by Telegram or email (design doc 13, F14): results filed, board meeting scheduled,
red-flag event, validation failure."""

import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from analekh.config import get_settings
from analekh.db.models import Alert

RED_FLAG_FEEDS = {"insider_trading", "encumbrance", "related_party"}


def send_telegram(text: str) -> bool:
    s = get_settings()
    if not (s.telegram_bot_token and s.telegram_chat_id):
        return False
    resp = httpx.post(
        f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
        json={"chat_id": s.telegram_chat_id, "text": text},
        timeout=15,
    )
    return resp.is_success


def send_email(subject: str, body: str) -> bool:
    """SMTP_URL like smtp://user:pass@host:587"""
    s = get_settings()
    if not (s.smtp_url and s.alert_email_to):
        return False
    url = urlparse(s.smtp_url)
    msg = EmailMessage()
    msg["Subject"], msg["To"] = subject, s.alert_email_to
    msg["From"] = url.username or "analekh@localhost"
    msg.set_content(body)
    with smtplib.SMTP(url.hostname or "localhost", url.port or 587, timeout=15) as smtp:
        smtp.starttls()
        if url.username:
            smtp.login(url.username, url.password or "")
        smtp.send_message(msg)
    return True


def raise_alert(
    session: Session, kind: str, company_id: int | None, text: str, payload: dict | None = None
) -> Alert:
    channel = "telegram" if send_telegram(text) else "email" if send_email(kind, text) else "none"
    alert = Alert(
        company_id=company_id,
        kind=kind,
        payload={"text": text, **(payload or {})},
        channel=channel,
        sent_at=datetime.now(UTC) if channel != "none" else None,
    )
    session.add(alert)
    return alert
