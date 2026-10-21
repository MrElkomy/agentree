"""Outbound email. SMTP in all environments (Mailpit in development)."""

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from agentree.core.config import Settings
from agentree.core.email_layout import LOGO_CID, EmailContent, clean_text, logo_png, render_email

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    body: str  # plain-text part (always sent)
    html: str | None = None  # branded HTML alternative; references the inline logo by CID


def branded_email(to: str, content: EmailContent) -> OutgoingEmail:
    """Build a multipart (text + HTML) email from the shared branded layout."""
    text, html = render_email(content)
    return OutgoingEmail(to=to, subject=clean_text(content.subject), body=text, html=html)


class EmailSender(Protocol):
    async def send(self, message: OutgoingEmail) -> None: ...


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def _send_sync(self, message: OutgoingEmail) -> None:
        msg = EmailMessage()
        msg["From"] = self._s.mail_from
        msg["To"] = message.to
        msg["Subject"] = clean_text(message.subject)
        msg.set_content(message.body)
        if message.html is not None:
            # multipart/alternative: text/plain + multipart/related(text/html + inline logo).
            msg.add_alternative(message.html, subtype="html")
            html_part = next(p for p in msg.iter_parts() if p.get_content_type() == "text/html")
            html_part.add_related(
                logo_png(), maintype="image", subtype="png", cid=f"<{LOGO_CID}>",
                filename="agentree-logo.png", disposition="inline",
            )  # fmt: skip
        with smtplib.SMTP(self._s.smtp_host, self._s.smtp_port, timeout=10) as smtp:
            if self._s.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self._s.smtp_username and self._s.smtp_password:
                smtp.login(self._s.smtp_username, self._s.smtp_password.get_secret_value())
            smtp.send_message(msg)

    async def send(self, message: OutgoingEmail) -> None:
        await asyncio.to_thread(self._send_sync, message)


async def send_safely(mailer: EmailSender, message: OutgoingEmail, *, kind: str) -> bool:
    """Send without failing the caller's request. Returns False if delivery failed.

    Every email flow is retryable by the user (resend verification, request reset again,
    re-invite), so a provider outage must not turn into a 500 or reveal account state.
    The recipient and body are never logged.
    """
    try:
        await mailer.send(message)
    except Exception as exc:
        logger.warning(
            "email delivery failed", extra={"kind": kind, "error_type": type(exc).__name__}
        )
        return False
    return True
