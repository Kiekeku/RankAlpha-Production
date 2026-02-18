from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Iterable, Optional


class EmailClient:
    """Minimal SMTP email client used across services.

    Configuration precedence:
      - Explicit kwargs passed to send()
      - SMTP_* environment variables
      - Gmail fallback via GMAIL_SENDER + GMAIL_APP_PASSWORD
    """

    @staticmethod
    def _default_sender() -> Optional[str]:
        return os.getenv("SMTP_FROM") or os.getenv("GMAIL_SENDER") or os.getenv("SMTP_USER")

    @staticmethod
    def _split_list(v: Optional[str]) -> list[str]:
        if not v:
            return []
        return [p.strip() for p in v.replace(";", ",").split(",") if p.strip()]

    @classmethod
    def send(
        cls,
        *,
        to: Iterable[str] | None,
        subject: str,
        text: Optional[str] = None,
        html: Optional[str] = None,
        sender: Optional[str] = None,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_secure: Optional[bool] = None,
        smtp_user: Optional[str] = None,
        smtp_pass: Optional[str] = None,
    ) -> None:
        if not text and not html:
            text = "(no content)"
        if sender is None:
            sender = cls._default_sender()
        if to is None:
            to = (
                cls._split_list(os.getenv("SMTP_TO_ALERTS"))
                or cls._split_list(os.getenv("BUDGET_ALERT_RECIPIENTS"))
                or cls._split_list(os.getenv("GMAIL_RECIPIENT"))
            )
        to_list = list(to or [])
        if not sender or not to_list:
            raise RuntimeError("email_not_configured: missing sender or recipients")

        # Resolve SMTP configuration
        host = smtp_host or os.getenv("SMTP_HOST")
        port = int(smtp_port or int(os.getenv("SMTP_PORT", "587")))
        secure = bool(
            smtp_secure
            if smtp_secure is not None
            else (os.getenv("SMTP_SECURE", "false").strip().lower() in {"1", "true", "yes"})
        )
        user = smtp_user or os.getenv("SMTP_USER")
        password = smtp_pass or os.getenv("SMTP_PASS")

        # Gmail fallback when explicit SMTP host not provided
        if not host:
            host = "smtp.gmail.com"
            port = 587
            secure = False
            if not password:
                password = os.getenv("GMAIL_APP_PASSWORD")
            if not user:
                user = sender

        # Build message
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = ", ".join(to_list)
        if html and text:
            msg.set_content(text)
            msg.add_alternative(html, subtype="html")
        elif html:
            msg.set_content("(HTML content)")
            msg.add_alternative(html, subtype="html")
        else:
            msg.set_content(text or "")

        if secure:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=10) as client:
                if user and password:
                    client.login(user, password)
                client.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=10) as client:
                client.ehlo()
                if client.has_extn("starttls"):
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                if user and password:
                    client.login(user, password)
                client.send_message(msg)
