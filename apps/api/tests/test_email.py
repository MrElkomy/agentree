"""SMTP sender against a minimal in-process SMTP server (same protocol Mailpit speaks)."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from agentree.core.config import Settings
from agentree.core.email import OutgoingEmail, SmtpEmailSender


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
                    lines.append(line)
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
