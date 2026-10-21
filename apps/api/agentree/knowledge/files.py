"""Knowledge file uploads (Task 17): store, check, extract into draft entries.

An upload is checked (`extract.sniff`: size, type from the content, archive safety), stored
tenant-scoped (RLS) and, for PDF/DOCX/TXT/MD, handed to an extraction child process with CPU,
memory and file-write limits and a timeout. Each section becomes a draft knowledge entry that
an Owner or Admin must publish (U-10: manual publish). CSV and XLSX are only stored (Task 18).
Files are never executed and only ever served back as attachments. File names and contents are
never logged.
"""

import asyncio
import hashlib
import json
import logging
import re
import resource
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.audit.service import AuditAction, record
from agentree.core.ids import uuid7
from agentree.knowledge.extract import (
    EXTRACTED_KINDS,
    FileRejectedError,
    Section,
    sniff,
)
from agentree.knowledge.models import KnowledgeEntry, KnowledgeFile, KnowledgeFileData
from agentree.knowledge.service import MAX_BODY_CHARS, NotFoundError, Status
from agentree.tenancy.context import TenantContext
from agentree.tenancy.db import tenant_session

logger = logging.getLogger(__name__)
Factory = async_sessionmaker[AsyncSession]

MAX_FILES_PER_BUSINESS = 100
MAX_BYTES_PER_BUSINESS = 200 * 1024 * 1024
EXTRACT_TIMEOUT_SECONDS = 60
CHILD_MEMORY_BYTES = 256 * 1024 * 1024
CHILD_CPU_SECONDS = 30
STALE_AFTER = timedelta(minutes=10)  # "processing" this long: the server restarted mid-way

# One extraction at a time per server process: bounded memory next to the API.
_slot = asyncio.Semaphore(1)
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\<>:\"|?*​-‏‪-‮⁦-⁩]")


class QuotaExceededError(Exception):
    pass


class InvalidStateError(Exception):
    pass


@dataclass(frozen=True)
class FileInfo:
    id: UUID
    filename: str
    kind: str
    size_bytes: int
    status: str  # processing | ready | stored | failed
    error: str | None
    entry_count: int
    created_at: datetime
    processed_at: datetime | None


def _now() -> datetime:
    return datetime.now(UTC)


def safe_filename(name: str) -> str:
    """Display name: no path, no control or bidi characters, at most 200 characters."""
    base = re.split(r"[/\\]", name)[-1]
    cleaned = " ".join(_UNSAFE_NAME.sub("", base).split()).strip(". ")
    return cleaned[:200] or "file"


def _title(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return (stem.replace("_", " ").replace("-", " ").strip() or "Uploaded file")[:120]


def _info(f: KnowledgeFile) -> FileInfo:
    status, error = f.status, f.error
    if status == "processing" and f.started_at < _now() - STALE_AFTER:
        status, error = "failed", "interrupted"
    return FileInfo(f.id, f.filename, f.kind, f.size_bytes, status, error, f.entry_count,
                    f.created_at, f.processed_at)  # fmt: skip


async def _get(session: AsyncSession, ctx: TenantContext, file_id: UUID) -> KnowledgeFile:
    f = (
        await session.execute(
            select(KnowledgeFile).where(KnowledgeFile.business_id == ctx.business_id,
                                        KnowledgeFile.id == file_id)
        )
    ).scalar_one_or_none()  # fmt: skip
    if f is None:
        raise NotFoundError
    return f


async def upload(
    factory: Factory, ctx: TenantContext, *, filename: str, data: bytes, actor_id: UUID
) -> FileInfo:
    """Check and store a file. Raises FileRejectedError (code) or QuotaExceededError. The
    caller then runs `process` for files whose status is `processing`."""
    name = safe_filename(filename)
    kind = sniff(name, data)
    now = _now()
    async with tenant_session(factory, ctx) as session:
        count, total = (
            await session.execute(
                select(func.count(), func.coalesce(func.sum(KnowledgeFile.size_bytes), 0))
                .where(KnowledgeFile.business_id == ctx.business_id)
            )
        ).one()  # fmt: skip
        if count >= MAX_FILES_PER_BUSINESS or total + len(data) > MAX_BYTES_PER_BUSINESS:
            raise QuotaExceededError
        f = KnowledgeFile(
            id=uuid7(), business_id=ctx.business_id, filename=name, kind=kind,
            size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
            status="processing" if kind in EXTRACTED_KINDS else "stored",
            uploaded_by_user_id=actor_id, created_at=now, started_at=now,
            processed_at=None if kind in EXTRACTED_KINDS else now,
        )  # fmt: skip
        session.add(f)
        await session.flush()
        session.add(KnowledgeFileData(file_id=f.id, business_id=ctx.business_id, data=data))
        await record(session, ctx, action=AuditAction.KNOWLEDGE_FILE_UPLOADED,
                     actor_user_id=actor_id, target_type="knowledge_file", target_id=f.id,
                     details={"kind": kind})  # fmt: skip
        return _info(f)


def _limits() -> None:  # runs in the child before exec
    resource.setrlimit(resource.RLIMIT_AS, (CHILD_MEMORY_BYTES, CHILD_MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (CHILD_CPU_SECONDS, CHILD_CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))  # it may not write files


async def run_extractor(kind: str, data: bytes, title: str) -> tuple[list[Section], str | None]:
    """Extract in a limited child process. Returns (sections, None) or ([], error code)."""
    async with _slot:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "agentree.knowledge.extract", kind, title,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, preexec_fn=_limits,
        )  # fmt: skip
        try:
            out, _ = await asyncio.wait_for(proc.communicate(data), EXTRACT_TIMEOUT_SECONDS)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return [], "too_complex"
    if proc.returncode != 0:  # killed by a limit (memory, CPU) or crashed
        return [], "too_complex"
    try:
        result = json.loads(out)
    except ValueError:
        return [], "damaged_file"
    if not result.get("ok"):
        return [], str(result.get("error") or "damaged_file")[:32]
    return [Section(str(s["title"]), str(s["text"])) for s in result["sections"]], None


async def process(factory: Factory, ctx: TenantContext, file_id: UUID, *, actor_id: UUID) -> None:
    """Extract a stored file into draft entries (background task after the upload)."""
    async with tenant_session(factory, ctx) as session:
        f = await _get(session, ctx, file_id)
        if f.status != "processing":
            return
        kind, title = f.kind, _title(f.filename)
        data = (
            await session.execute(
                select(KnowledgeFileData.data).where(
                    KnowledgeFileData.business_id == ctx.business_id,
                    KnowledgeFileData.file_id == file_id)
            )
        ).scalar_one()  # fmt: skip
    try:
        sections, error = await run_extractor(kind, data, title)
    except Exception as exc:  # the file stays failed; details never include its content
        logger.warning("knowledge extraction failed", extra={"error_type": type(exc).__name__})
        sections, error = [], "damaged_file"
    now = _now()
    async with tenant_session(factory, ctx) as session:
        f = await _get(session, ctx, file_id)
        for s in sections:
            session.add(KnowledgeEntry(
                id=uuid7(), business_id=ctx.business_id, title=s.title[:200],
                body=s.text[:MAX_BODY_CHARS], status=Status.DRAFT, agent_roles=[],
                created_by_user_id=actor_id, source_file_id=file_id, updated_at=now,
            ))  # fmt: skip
        f.status = "failed" if error else "ready"
        f.error, f.entry_count, f.processed_at = error, len(sections), now


async def list_files(factory: Factory, ctx: TenantContext) -> list[FileInfo]:
    async with tenant_session(factory, ctx) as session:
        rows = (
            await session.execute(
                select(KnowledgeFile).where(KnowledgeFile.business_id == ctx.business_id)
                .order_by(KnowledgeFile.created_at.desc())
            )
        ).scalars().all()  # fmt: skip
    return [_info(f) for f in rows]


async def get_file(factory: Factory, ctx: TenantContext, file_id: UUID) -> FileInfo:
    async with tenant_session(factory, ctx) as session:
        return _info(await _get(session, ctx, file_id))


async def retry(factory: Factory, ctx: TenantContext, file_id: UUID) -> FileInfo:
    """A failed (or interrupted) extraction runs again; the caller schedules `process`."""
    async with tenant_session(factory, ctx) as session:
        f = await _get(session, ctx, file_id)
        if f.kind not in EXTRACTED_KINDS or _info(f).status != "failed":
            raise InvalidStateError
        f.status, f.error, f.started_at = "processing", None, _now()
        return _info(f)


async def download(factory: Factory, ctx: TenantContext, file_id: UUID) -> tuple[str, bytes]:
    async with tenant_session(factory, ctx) as session:
        f = await _get(session, ctx, file_id)
        data = (
            await session.execute(
                select(KnowledgeFileData.data).where(
                    KnowledgeFileData.business_id == ctx.business_id,
                    KnowledgeFileData.file_id == file_id)
            )
        ).scalar_one()  # fmt: skip
        return f.filename, data


async def delete_file(factory: Factory, ctx: TenantContext, file_id: UUID, *,
                      actor_id: UUID) -> None:  # fmt: skip
    """Delete the file and its bytes. Entries extracted from it stay (they are reviewed text)."""
    async with tenant_session(factory, ctx) as session:
        f = await _get(session, ctx, file_id)
        await session.execute(
            delete(KnowledgeFile).where(KnowledgeFile.business_id == ctx.business_id,
                                        KnowledgeFile.id == file_id)
        )  # fmt: skip
        await record(session, ctx, action=AuditAction.KNOWLEDGE_FILE_DELETED,
                     actor_user_id=actor_id, target_type="knowledge_file", target_id=file_id,
                     details={"kind": f.kind})  # fmt: skip


__all__ = ["FileRejectedError", "NotFoundError"]
