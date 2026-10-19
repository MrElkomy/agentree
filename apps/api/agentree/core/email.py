"""Outbound email. SMTP in all environments (Mailpit in development)."""

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from agentree.core.config import Settings


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    async def send(self, message: OutgoingEmail) -> None: ...


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def _send_sync(self, message: OutgoingEmail) -> None:
        msg = EmailMessage()
        msg["From"] = self._s.mail_from
        msg["To"] = message.to
        msg["Subject"] = message.subject
        msg.set_content(message.body)
        with smtplib.SMTP(self._s.smtp_host, self._s.smtp_port, timeout=10) as smtp:
            if self._s.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self._s.smtp_username and self._s.smtp_password:
                smtp.login(self._s.smtp_username, self._s.smtp_password.get_secret_value())
            smtp.send_message(msg)

    async def send(self, message: OutgoingEmail) -> None:
        await asyncio.to_thread(self._send_sync, message)
