"""Email report settings (Task 20c). Members read them; Owners and Admins change them and can
send themselves a test report now."""

from fastapi import APIRouter, HTTPException, Request, status

from agentree.core import ratelimit
from agentree.reports import service
from agentree.reports.schemas import ReportSettingsIO, TestSendOut
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role

router = APIRouter(prefix="/api/businesses/{business_id}/report-settings", tags=["reports"])

TEST_SENDS_PER_HOUR = 5


def _out(s: service.SettingsInfo) -> ReportSettingsIO:
    return ReportSettingsIO(frequency=s.frequency, weekday=s.weekday,
                            include_notes=s.include_notes, last_sent_at=s.last_sent_at)  # fmt: skip


def _deps(request: Request) -> service.Deps:
    st = request.app.state
    return service.Deps(st.settings, st.mailer, st.push, st.vault, st.llm_providers)


@router.get("")
async def get_report_settings(member: Member, request: Request) -> ReportSettingsIO:
    return _out(await service.get_settings(request.app.state.session_factory, member.tenant))


@router.put("")
async def put_report_settings(
    body: ReportSettingsIO, member: Member, request: Request
) -> ReportSettingsIO:
    member.require(Role.ADMIN)
    saved = await service.save_settings(
        request.app.state.session_factory, member.tenant, frequency=body.frequency,
        weekday=body.weekday, include_notes=body.include_notes, actor_id=member.user.id,
    )  # fmt: skip
    return _out(saved)


@router.post("/test", status_code=status.HTTP_202_ACCEPTED)
async def send_test_report(member: Member, request: Request) -> TestSendOut:
    """Email the report to yourself now (weekly when reports are off). 429 `busy`."""
    member.require(Role.ADMIN)
    factory = request.app.state.session_factory
    if not await ratelimit.hit(factory, ratelimit.key_for("report-test:user", str(member.user.id)),
                               limit=TEST_SENDS_PER_HOUR, window_seconds=3600):  # fmt: skip
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "busy")
    s = await service.get_settings(factory, member.tenant)
    sent = await service.send(factory, member.tenant, _deps(request), s.frequency,
                              daily_budget=200, only_to=member.user.email)  # fmt: skip
    return TestSendOut(sent=sent)
