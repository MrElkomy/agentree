"""Knowledge file uploads (Task 17). Members upload (drafts need an admin to publish); Owners
and Admins delete. Downloads are always attachments, never rendered."""

from dataclasses import asdict
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response

from agentree.core import ratelimit
from agentree.knowledge import files
from agentree.knowledge.extract import MAX_FILE_BYTES
from agentree.knowledge.schemas import KnowledgeFileOut
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role

router = APIRouter(prefix="/api/businesses/{business_id}/knowledge-files", tags=["knowledge"])

UPLOADS_PER_USER_PER_HOUR = 30


def _out(f: files.FileInfo) -> KnowledgeFileOut:
    return KnowledgeFileOut(**asdict(f))


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "not_found")


@router.get("")
async def list_files(member: Member, request: Request) -> list[KnowledgeFileOut]:
    return [_out(f) for f in await files.list_files(request.app.state.session_factory,
                                                    member.tenant)]  # fmt: skip


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_file(
    member: Member, request: Request, tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="PDF, DOCX, TXT, MD, CSV or XLSX, up to 10 MB")],
) -> KnowledgeFileOut:  # fmt: skip
    """Store a file; PDF/DOCX/TXT/MD are then turned into draft entries in the background.

    413 `file_too_large`; 422 `unsupported_type`, `type_mismatch`, `not_utf8`, `empty_file`,
    `unsafe_archive`, `damaged_file`; 409 `quota_exceeded`; 429 `busy`.
    """
    factory = request.app.state.session_factory
    if not await ratelimit.hit(factory, ratelimit.key_for("knowledge-upload:user",
                                                          str(member.user.id)),
                               limit=UPLOADS_PER_USER_PER_HOUR, window_seconds=3600):  # fmt: skip
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "busy")
    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large")
    try:
        info = await files.upload(factory, member.tenant, filename=file.filename or "file",
                                  data=data, actor_id=member.user.id)  # fmt: skip
    except files.FileRejectedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except files.QuotaExceededError:
        raise HTTPException(status.HTTP_409_CONFLICT, "quota_exceeded") from None
    if info.status == "processing":
        tasks.add_task(files.process, factory, member.tenant, info.id, actor_id=member.user.id)
    return _out(info)


@router.get("/{file_id}")
async def get_file(file_id: UUID, member: Member, request: Request) -> KnowledgeFileOut:
    try:
        return _out(await files.get_file(request.app.state.session_factory, member.tenant,
                                         file_id))  # fmt: skip
    except files.NotFoundError:
        raise _not_found() from None


@router.post("/{file_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_file(
    file_id: UUID, member: Member, request: Request, tasks: BackgroundTasks
) -> KnowledgeFileOut:
    factory = request.app.state.session_factory
    try:
        info = await files.retry(factory, member.tenant, file_id)
    except files.NotFoundError:
        raise _not_found() from None
    except files.InvalidStateError:
        raise HTTPException(status.HTTP_409_CONFLICT, "file_state") from None
    tasks.add_task(files.process, factory, member.tenant, info.id, actor_id=member.user.id)
    return _out(info)


@router.get("/{file_id}/download", response_class=Response,
            responses={200: {"content": {"application/octet-stream": {}}}})  # fmt: skip
async def download_file(file_id: UUID, member: Member, request: Request) -> Response:
    try:
        name, data = await files.download(request.app.state.session_factory, member.tenant,
                                          file_id)  # fmt: skip
    except files.NotFoundError:
        raise _not_found() from None
    return Response(data, media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, no-store",
    })  # fmt: skip


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(file_id: UUID, member: Member, request: Request) -> None:
    member.require(Role.ADMIN)
    try:
        await files.delete_file(request.app.state.session_factory, member.tenant, file_id,
                                actor_id=member.user.id)  # fmt: skip
    except files.NotFoundError:
        raise _not_found() from None
