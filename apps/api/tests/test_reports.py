"""Email reports and alerts (Task 20c): settings, report numbers from computed metrics, checked
Executive notes, scheduled sending once per period, the daily-budget alert and the
"visitor still waiting" alert."""

import uuid
from datetime import timedelta
from typing import Any

import pytest

from agentree.analytics import service as analytics
from agentree.reports import service as reports
from agentree.tenancy.context import TenantContext, TenantSource
from tests.conftest import AppHarness, DbUrls, _admin_execute
from tests.helpers import invite_and_join
from tests.test_agents import Biz, _configure, _fake, _say
from tests.test_analytics import _activity
from tests.test_support_agents import CS, SALES, _support_business, _visitor


def _deps(h: AppHarness) -> reports.Deps:
    st = h.app.state
    return reports.Deps(st.settings, h.mailer, h.push, st.vault, st.llm_providers)


def _ctx(biz: Biz) -> TenantContext:
    return TenantContext(uuid.UUID(biz.id), TenantSource.JOB)


async def _settings(biz: Biz, **body: Any) -> Any:
    return await biz.owner.client.put(f"{biz.base}/report-settings",
                                      json={"frequency": "weekly"} | body)  # fmt: skip


def _to(h: AppHarness, address: str, since: int = 0, *, kind: str = "") -> list[Any]:
    return [m for m in h.mailer.sent[since:] if m.to == address and kind in m.subject]


# --- settings -----------------------------------------------------------------------------------


async def test_settings_default_off_and_admins_change_them(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    got = (await biz.owner.client.get(f"{biz.base}/report-settings")).json()
    assert got == {"frequency": "off", "weekday": 0, "include_notes": False, "last_sent_at": None}
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    r = await member.client.put(f"{biz.base}/report-settings", json={"frequency": "daily"})
    assert r.status_code == 403
    assert (await member.client.post(f"{biz.base}/report-settings/test")).status_code == 403
    r = await _settings(biz, weekday=7)
    assert r.status_code == 422
    r = await _settings(biz, weekday=2, include_notes=True)
    assert r.status_code == 200 and r.json()["weekday"] == 2 and r.json()["include_notes"]
    events = (await biz.owner.client.get(f"{biz.base}/audit-events")).json()["events"]
    assert any(e["action"] == "report_settings.updated" for e in events)


# --- the report ---------------------------------------------------------------------------------


async def test_report_numbers_come_from_computed_metrics(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    await _activity(harness, biz)  # 2 conversations, 1 lead, 1 handoff (resolved)
    await analytics.compute_due(harness.app.state.session_factory)
    tomorrow = analytics.utc_today() + timedelta(days=1)
    report = await reports.build(harness.app.state.session_factory, _ctx(biz), "daily",
                                 today=tomorrow)  # fmt: skip
    assert report.title == "Daily report"
    assert f"Yesterday ({analytics.utc_today().isoformat()})" == report.period
    assert "Visitor conversations: 2 (period before: 0)" in report.lines
    assert "New leads: 1 (period before: 0)" in report.lines
    assert "Leads still new: 1" in report.lines
    assert "Requests waiting for your approval: 0" in report.lines
    assert report.notes == []


async def test_test_send_goes_only_to_the_requester(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    admin = await invite_and_join(harness, biz.owner, biz.id, "admin")
    before = len(harness.mailer.sent)
    r = await biz.owner.client.post(f"{biz.base}/report-settings/test")
    assert r.status_code == 202 and r.json() == {"sent": 1}
    (email,) = harness.mailer.sent[before:]
    assert email.to == biz.owner.email and "weekly report" in email.subject
    assert "Visitor conversations:" in email.body and "/analytics" in email.body
    assert _to(harness, admin.email, before) == []


async def test_executive_notes_are_checked(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    await _settings(biz, include_notes=True)
    # Notes only when the Executive Assistant is on.
    before = len(harness.mailer.sent)
    await biz.owner.client.post(f"{biz.base}/report-settings/test")
    assert "Notes from your Executive Assistant" not in harness.mailer.sent[-1].body
    await _configure(biz, "executive", enabled=True, public=False)
    _fake(harness).replies.append("- Visitor conversations: 0 this week.\n- Share your page.")
    before = len(harness.mailer.sent)
    await biz.owner.client.post(f"{biz.base}/report-settings/test")
    body = harness.mailer.sent[before:][0].body
    assert "Notes from your Executive Assistant" in body and "Share your page." in body
    # An invented number drops the notes, never the report.
    _fake(harness).replies.append("- You will get 50 leads next week.")
    before = len(harness.mailer.sent)
    await biz.owner.client.post(f"{biz.base}/report-settings/test")
    body = harness.mailer.sent[before:][0].body
    assert "Notes from your Executive Assistant" not in body and "50 leads" not in body
    assert "Visitor conversations:" in body


async def test_scheduled_reports_go_once_per_period(
    harness: AppHarness, db_urls: DbUrls, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reports, "REPORT_HOUR", 0)  # due any time of day in tests
    biz = await _support_business(harness)
    admin = await invite_and_join(harness, biz.owner, biz.id, "admin")
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    other = await _support_business(harness, name="Other Shop")  # reports off
    await biz.owner.client.put(f"{biz.base}/report-settings", json={"frequency": "daily"})
    factory = harness.app.state.session_factory
    before = len(harness.mailer.sent)
    await reports.run_due(factory, _deps(harness))
    sent = [m for m in harness.mailer.sent[before:] if "daily report" in m.subject]
    assert sorted(m.to for m in sent) == sorted([biz.owner.email, admin.email])
    assert member.email not in [m.to for m in sent] and other.owner.email not in [
        m.to for m in sent
    ]
    again = len(harness.mailer.sent)
    await reports.run_due(factory, _deps(harness))
    assert [m for m in harness.mailer.sent[again:] if "report" in m.subject] == []
    # Weekly on another weekday: not today.
    weekday = (analytics.utc_today().weekday() + 3) % 7
    await _settings(biz, weekday=weekday)
    await _admin_execute(db_urls.admin, "UPDATE report_settings SET last_sent_at = NULL "
                         f"WHERE business_id = '{biz.id}'")  # fmt: skip
    later = len(harness.mailer.sent)
    await reports.run_due(factory, _deps(harness))
    assert [m for m in harness.mailer.sent[later:] if "report" in m.subject] == []


# --- alerts -------------------------------------------------------------------------------------


async def test_budget_alert_once_a_day(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    r = await biz.owner.client.put(f"{biz.base}/public-profile", json={
        "enabled": True, "daily_reply_budget": 1})  # fmt: skip
    assert r.status_code == 200, r.text
    c, auth = await _visitor(harness, biz)
    _fake(harness).replies.append("Hello!")
    conv = (await _say(c, biz, auth, "Hi", agent=SALES)).json()["conversation_id"]
    before = len(harness.mailer.sent)
    for _ in range(3):
        r = await _say(c, biz, auth, "Again?", conv)
        assert r.status_code == 429
    alerts = [m for m in harness.mailer.sent[before:] if "AI reply budget" in m.subject]
    assert [m.to for m in alerts] == [biz.owner.email]
    assert "/public-page" in alerts[0].body and "Again?" not in alerts[0].body


async def test_waiting_visitor_alert_once(harness: AppHarness, db_urls: DbUrls) -> None:
    biz = await _support_business(harness)
    c, auth = await _visitor(harness, biz)
    _fake(harness).replies.append("Connecting you.\n<<HANDOFF>>")
    conv = (await _say(c, biz, auth, "A person please", agent=CS)).json()["conversation_id"]
    factory = harness.app.state.session_factory
    before = len(harness.mailer.sent)
    await reports.run_due(factory, _deps(harness))
    assert [m for m in harness.mailer.sent[before:] if "waited" in m.subject] == []  # too soon
    await _admin_execute(db_urls.admin, "UPDATE conversations SET handoff_requested_at = now() "
                         f"- interval '31 minutes' WHERE id = '{conv}'")  # fmt: skip
    await reports.run_due(factory, _deps(harness))
    alerts = [m for m in harness.mailer.sent[before:] if "waited 30 minutes" in m.subject]
    assert [m.to for m in alerts] == [biz.owner.email]
    assert f"/inbox/{conv}" in alerts[0].body and "A person please" not in alerts[0].body
    again = len(harness.mailer.sent)
    await reports.run_due(factory, _deps(harness))
    assert [m for m in harness.mailer.sent[again:] if "waited" in m.subject] == []


@pytest.mark.parametrize("sql", [
    "SELECT * FROM agentree_claim_due_reports(25, 10)",
    "SELECT * FROM agentree_claim_due_reports(8, 0)",
    "SELECT * FROM agentree_claim_waiting_alerts(NULL, 10)",
    "SELECT * FROM agentree_claim_waiting_alerts(now(), 501)",
])  # fmt: skip
async def test_claim_functions_refuse_bad_arguments(harness: AppHarness, sql: str) -> None:
    from sqlalchemy import text

    with pytest.raises(Exception, match="invalid"):
        async with harness.app.state.session_factory() as session, session.begin():
            await session.execute(text(sql))
