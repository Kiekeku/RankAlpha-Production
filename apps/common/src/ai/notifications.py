from __future__ import annotations

import logging
from dataclasses import dataclass

from apps.common.src.email.client import EmailClient

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency in slim test envs
    from apps.common.src.settings import Settings as _Settings
except Exception:  # pragma: no cover
    _Settings = None


@dataclass
class BudgetAlertEvent:
    service: str
    metric: str  # e.g., "tokens" or "cost"
    threshold: float  # 0.8 or 1.0
    percent: float
    used: float
    limit: float
    date_utc: str


def _split_recipients(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
    return parts


def send_budget_alert(event: BudgetAlertEvent) -> None:
    """Send an email alert when usage crosses a configured budget threshold."""

    settings = _Settings() if _Settings is not None else None
    if settings is None:
        logger.warning("Budget alert suppressed: settings module unavailable")
        return
    recipients = _split_recipients(settings.budget_alert_recipients) or _split_recipients(
        settings.gmail_recipient
    )
    if not recipients:
        logger.warning(
            "Budget alert for service=%s metric=%s suppressed: no recipients configured",
            event.service,
            event.metric,
        )
        return

    subject = f"[RankAlpha] {event.service} {event.metric} usage {int(event.threshold * 100)}%"
    percent_display = f"{event.percent:.1%}" if event.percent else f"{event.threshold:.0%}"
    body = (
        f"Service: {event.service}\n"
        f"Metric: {event.metric}\n"
        f"Date (UTC): {event.date_utc}\n"
        f"Usage: {event.used:.2f} / {event.limit:.2f} ({percent_display})\n"
        f"Threshold crossed: {int(event.threshold * 100)}%\n"
    )

    try:
        EmailClient.send(to=recipients, subject=subject, text=body, sender=None)
        logger.info(
            "Budget alert email sent",
            extra={"service": event.service, "metric": event.metric, "threshold": event.threshold},
        )
    except Exception as exc:
        logger.exception(
            "Failed to send budget alert email",
            extra={
                "service": event.service,
                "metric": event.metric,
                "threshold": event.threshold,
                "error": str(exc),
            },
        )
