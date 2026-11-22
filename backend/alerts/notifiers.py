"""Email (SMTP) notification dispatcher with safe console fallback."""
import asyncio
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import List, Optional

from config import settings

logger = logging.getLogger("frost_ioe.alerts")
MYT = timezone(timedelta(hours=8))


def _fmt_myt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MYT).strftime("%Y-%m-%d %H:%M:%S MYT")


def format_email(event: dict) -> tuple[str, str]:
    """Build (subject, plain-text body) for an alert or recovery event."""
    severity = event["severity"]
    zone_label = event.get("zone_name") or event["zone_id"]
    alert_type = event["alert_type"].replace("_", " ").title()

    if event["state"] == "RESOLVED":
        subject = f"[Frost-IoE RECOVERY] {zone_label} — {alert_type} Resolved"
    else:
        subject = f"[Frost-IoE {severity}] {zone_label} — {alert_type}"

    lines = [
        f"System:   Frost-IoE Cold Storage Monitor",
        f"Status:   {event['state']} ({severity})",
        f"Zone:     {zone_label} ({event['zone_id']})",
    ]
    if event.get("node_id") and event["node_id"] != "zone_aggregate":
        node_label = event.get("node_name") or event["node_id"]
        lines.append(f"Node:     {node_label} ({event['node_id']})")
    lines.append(f"Time:     {_fmt_myt(event.get('timestamp'))}")
    lines.append("")
    lines.append(event["message"])

    details = []
    if event.get("temp_c") is not None:
        details.append(f"Current Temp: {event['temp_c']:.2f} °C")
    if event.get("limit_c") is not None:
        details.append(f"Limit:        {event['limit_c']:.2f} °C")
    if event.get("peak_c") is not None:
        details.append(f"Peak Temp:    {event['peak_c']:.2f} °C")
    if event.get("duration_minutes") is not None:
        details.append(f"Duration:     {event['duration_minutes']:.1f} min")
    if details:
        lines.append("")
        lines.extend(details)

    return subject, "\n".join(lines)


class EmailNotifier:
    """Sends alert emails via SMTP STARTTLS/SSL, or logs to console when disabled/unconfigured."""

    def __init__(self, enabled: Optional[bool] = None):
        self.enabled = settings.EMAIL_ALERTS_ENABLED if enabled is None else enabled

    def is_configured(self) -> bool:
        return bool(settings.SMTP_HOST and settings.ALERT_RECIPIENTS)

    def send_sync(self, event: dict) -> bool:
        subject, body = format_email(event)
        if not self.enabled or not self.is_configured():
            logger.warning("[Alert Console Fallback] %s\n%s", subject, body)
            return False

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.ALERT_FROM_EMAIL or settings.SMTP_USER or "frost-ioe@localhost"
        msg["To"] = ", ".join(settings.ALERT_RECIPIENTS)
        msg.set_content(body)

        try:
            if settings.SMTP_PORT == 465 and not settings.SMTP_USE_TLS:
                with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                    if settings.SMTP_USER and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                    server.ehlo()
                    if settings.SMTP_USE_TLS:
                        server.starttls()
                        server.ehlo()
                    if settings.SMTP_USER and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.send_message(msg)
            logger.info("Sent alert email: %s -> %s", subject, msg["To"])
            return True
        except Exception as exc:
            logger.error("Failed to send alert email '%s': %s", subject, exc)
            return False

    async def send(self, event: dict) -> bool:
        return await asyncio.to_thread(self.send_sync, event)

    def send_test_email(self, recipients: Optional[List[str]] = None) -> dict:
        event = {
            "timestamp": datetime.now(timezone.utc),
            "zone_id": "SYSTEM",
            "zone_name": "System Check",
            "node_id": "zone_aggregate",
            "alert_type": "test_notification",
            "severity": "INFO",
            "state": "ALERTING",
            "message": "This is a test notification from Frost-IoE confirming SMTP email delivery.",
        }
        prev_enabled = self.enabled
        prev_recipients = settings.ALERT_RECIPIENTS
        try:
            if recipients:
                settings.ALERT_RECIPIENTS = recipients
            self.enabled = True
            sent = self.send_sync(event)
            return {
                "email_sent": sent,
                "configured": self.is_configured(),
                "recipients": list(settings.ALERT_RECIPIENTS),
            }
        finally:
            self.enabled = prev_enabled
            settings.ALERT_RECIPIENTS = prev_recipients
