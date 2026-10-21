"""SMTP sender against a minimal in-process SMTP server (same protocol Mailpit speaks)."""

import asyncio
import email
import email.policy
from collections.abc import AsyncIterator
from email.message import EmailMessage

import pytest

from agentree.core.config import Settings
from agentree.core.email import OutgoingEmail, SmtpEmailSender, branded_email
from agentree.core.email_layout import EmailAction, EmailContent, logo_png


class _MiniSmtp:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"220 mini ESMTP\r\n")
        data_mode = False
        lines: list[bytes] = []
        while line := await reader.readline():
            if data_mode:
                if line == b".\r\n":
                    self.messages.append(b"".join(lines).decode())
                    data_mode = False
                    lines = []
                    writer.write(b"250 queued\r\n")
                else:
                    lines.append(line[1:] if line.startswith(b"..") else line)  # dot-unstuffing
                continue
            cmd = line.decode().strip().upper()
            if cmd.startswith(("EHLO", "HELO")):
                writer.write(b"250 mini\r\n")
            elif cmd == "DATA":
                data_mode = True
                writer.write(b"354 go\r\n")
            elif cmd == "QUIT":
                writer.write(b"221 bye\r\n")
                await writer.drain()
                break
            else:
                writer.write(b"250 ok\r\n")
            await writer.drain()
        writer.close()


@pytest.fixture
async def smtp_server() -> AsyncIterator[tuple[_MiniSmtp, int]]:
    mini = _MiniSmtp()
    server = await asyncio.start_server(mini.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield mini, port


async def test_smtp_sender_delivers_message(smtp_server: tuple[_MiniSmtp, int]) -> None:
    mini, port = smtp_server
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@h/d", smtp_host="127.0.0.1", smtp_port=port,
        mail_from="Agentree <no-reply@agentree.test>",
    )  # fmt: skip
    await SmtpEmailSender(settings).send(
        OutgoingEmail(to="owner@example.com", subject="Hello", body="Body text")
    )
    assert len(mini.messages) == 1
    msg = mini.messages[0]
    assert "To: owner@example.com" in msg
    assert "Subject: Hello" in msg
    assert "Body text" in msg


def _settings(port: int) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@h/d", smtp_host="127.0.0.1", smtp_port=port,
        mail_from="Agentree <no-reply@agentree.test>",
    )  # fmt: skip


def _parse(raw: str) -> EmailMessage:
    msg = email.message_from_string(raw, policy=email.policy.default)
    assert isinstance(msg, EmailMessage)
    return msg


async def test_smtp_sender_sends_html_alternative_with_inline_logo(
    smtp_server: tuple[_MiniSmtp, int],
) -> None:
    mini, port = smtp_server
    content = EmailContent(
        subject="Confirm\r\nBcc: x@example.com",
        preheader="Preheader",
        heading="Confirm your email",
        paragraphs=["Thanks for signing up."],
        action=EmailAction("Confirm email", "https://app.example/verify-email?token=TOK123"),
    )
    await SmtpEmailSender(_settings(port)).send(branded_email("owner@example.com", content))
    assert len(mini.messages) == 1
    msg = _parse(mini.messages[0])
    assert msg["Subject"] == "Confirm Bcc: x@example.com"
    assert msg["Bcc"] is None
    assert msg.get_content_type() == "multipart/alternative"
    plain, related = list(msg.iter_parts())
    assert plain.get_content_type() == "text/plain"
    assert "https://app.example/verify-email?token=TOK123" in plain.get_content().splitlines()
    assert related.get_content_type() == "multipart/related"
    html_part, logo = list(related.iter_parts())
    assert html_part.get_content_type() == "text/html"
    assert "cid:agentree-logo" in html_part.get_content()
    assert logo.get_content_type() == "image/png"
    assert logo["Content-ID"] == "<agentree-logo>"
    assert logo.get_content_disposition() == "inline"
    assert logo.get_content() == logo_png()


async def test_smtp_sender_plain_text_only_is_unchanged(
    smtp_server: tuple[_MiniSmtp, int],
) -> None:
    mini, port = smtp_server
    await SmtpEmailSender(_settings(port)).send(
        OutgoingEmail(to="owner@example.com", subject="Hello", body="Body text")
    )
    msg = _parse(mini.messages[0])
    assert msg.get_content_type() == "text/plain"
    assert not msg.is_multipart()
    assert msg.get_content().strip() == "Body text"
