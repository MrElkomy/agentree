"""Analytics (Task 18): the monthly summary and its Excel export. Members read; the export
includes the leads sheet (contact details) only for Owners and Admins."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response

from agentree.analytics import export, service
from agentree.analytics.schemas import DayOut, MetricOut, RateOut, SummaryOut
from agentree.tenancy import service as tenancy
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role, at_least

router = APIRouter(prefix="/api/businesses/{business_id}/analytics", tags=["analytics"])

Month = Annotated[str, Query(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM (UTC)")]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _bad_month() -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_month")


@router.get("/summary")
async def monthly_summary(month: Month, member: Member, request: Request) -> SummaryOut:
    try:
        start, end = service.month_range(month)
        s = await service.summary(request.app.state.session_factory, member.tenant, start, end)
    except service.InvalidRangeError:
        raise _bad_month() from None
    return SummaryOut(
        start=s.start, end=s.end,
        totals=[MetricOut(name=m, label=service.METRICS[m], value=v) for m, v in s.totals.items()],
        rates=[RateOut(name=r, label=service.RATE_LABELS[r], value=v) for r, v in s.rates.items()],
        days=[DayOut(day=d.day, values=d.values) for d in s.days], missing_days=s.missing_days,
    )  # fmt: skip


@router.get("/export", response_class=Response,
            responses={200: {"content": {XLSX: {}}}})  # fmt: skip
async def monthly_export(month: Month, member: Member, request: Request) -> Response:
    factory = request.app.state.session_factory
    business = await tenancy.get_business(factory, member.tenant)
    try:
        data = await export.monthly_workbook(
            factory, member.tenant, month, business_name=business.name,
            include_leads=at_least(member.role, Role.ADMIN),
        )  # fmt: skip
    except service.InvalidRangeError:
        raise _bad_month() from None
    return Response(data, media_type=XLSX, headers={
        "Content-Disposition": f'attachment; filename="agentree-{business.slug}-{month}.xlsx"',
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
    })  # fmt: skip
