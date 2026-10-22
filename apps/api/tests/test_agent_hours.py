"""Business hours and agent availability (Task 20b): always / during business hours / outside
them, pauses with a fixed message; visitors get that message instead of an AI reply (no
provider call), the test chat is unaffected, and the metrics count it apart from AI replies."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agentree.agents import hours
from agentree.agents.registry import AgentRole
from agentree.analytics import service as analytics
from tests.conftest import AppHarness
from tests.helpers import invite_and_join
from tests.test_agents import Biz, _fake, _say
from tests.test_support_agents import SALES, _support_business, _visitor

NINE_TO_FIVE = [{"start": "09:00", "end": "17:00"}] * 5 + [None, None]
CLOSED = [None] * 7


def _hours(tz: str, days: list[Any]) -> hours.HoursInfo:
    return hours.HoursInfo(tz, hours.validate_days(days), None)


def _avail(mode: str = "always", **over: Any) -> hours.Availability:
    base = hours.Availability(AgentRole.SALES, mode, "", None, None, "", None)
    return hours.Availability(**{**base.__dict__, **over})


async def _set_hours(biz: Biz, days: list[Any], tz: str = "Africa/Cairo") -> Any:
    return await biz.owner.client.put(f"{biz.base}/business-hours",
                                      json={"timezone": tz, "days": days})  # fmt: skip


async def _set_availability(biz: Biz, role: str = SALES, **body: Any) -> Any:
    return await biz.owner.client.put(f"{biz.agents}/{role}/availability",
                                      json={"mode": "always"} | body)  # fmt: skip


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


# --- the rules (pure) ---------------------------------------------------------------------------


def test_open_hours_use_the_business_time_zone() -> None:
    cairo = _hours("Africa/Cairo", NINE_TO_FIVE)
    # Monday 2026-10-19 08:30 UTC is 11:30 in Cairo (UTC+3 in October 2026).
    monday = datetime(2026, 10, 19, 8, 30, tzinfo=UTC)
    assert hours.is_open(cairo, monday)
    assert not hours.is_open(cairo, monday.replace(hour=14, minute=30))  # 17:30 local
    assert not hours.is_open(cairo, datetime(2026, 10, 24, 8, 30, tzinfo=UTC))  # Saturday


def test_modes_and_pauses() -> None:
    cairo = _hours("Africa/Cairo", NINE_TO_FIVE)
    open_now = datetime(2026, 10, 19, 8, 30, tzinfo=UTC)
    closed_now = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
    assert hours.away_message(_avail("always"), cairo, closed_now) is None
    assert hours.away_message(_avail("business_hours"), cairo, open_now) is None
    assert hours.away_message(_avail("business_hours"), cairo, closed_now) == hours.DEFAULT_AWAY
    assert hours.away_message(_avail("outside_business_hours"), cairo, closed_now) is None
    assert hours.away_message(_avail("outside_business_hours", away_message="Team's in!"),
                              cairo, open_now) == "Team's in!"  # fmt: skip
    eid = _avail("always", paused_from=open_now - timedelta(days=1),
                 paused_until=open_now + timedelta(days=2), pause_message="Eid Mubarak!")  # fmt: skip
    assert hours.away_message(eid, cairo, open_now) == "Eid Mubarak!"
    assert hours.away_message(eid, cairo, open_now + timedelta(days=3)) is None  # over
    assert hours.away_message(_avail("business_hours"), None, closed_now) is None  # no hours


@pytest.mark.parametrize("days", [
    NINE_TO_FIVE[:6], [{"start": "17:00", "end": "09:00"}] + [None] * 6,
    [{"start": "9am", "end": "5pm"}] + [None] * 6, ["open"] + [None] * 6,
])  # fmt: skip
def test_invalid_days_are_refused(days: list[Any]) -> None:
    with pytest.raises(hours.InvalidHoursError):
        hours.validate_days(days)


def test_messages_are_plain_single_paragraphs() -> None:
    assert hours.validate_message("Back\non <<Sunday>>!\u2028") == "Back on Sunday!"
    with pytest.raises(hours.InvalidHoursError):
        hours.validate_message("x" * 501)


# --- API ----------------------------------------------------------------------------------------


async def test_business_hours_api(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    got = (await biz.owner.client.get(f"{biz.base}/business-hours")).json()
    assert got["configured"] is False and got["timezone"] == "UTC"
    assert (await _set_hours(biz, NINE_TO_FIVE, "Mars/Olympus")).json()["detail"] == (
        "invalid_timezone")  # fmt: skip
    r = await _set_hours(biz, [{"start": "18:00", "end": "08:00"}] + [None] * 6)
    assert r.status_code == 422 and r.json()["detail"] == "invalid_days"
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    r = await member.client.put(f"{biz.base}/business-hours",
                                json={"timezone": "UTC", "days": NINE_TO_FIVE})  # fmt: skip
    assert r.status_code == 403
    r = await _set_hours(biz, NINE_TO_FIVE)
    assert r.status_code == 200 and r.json() == {"timezone": "Africa/Cairo",
                                                 "days": NINE_TO_FIVE, "configured": True}  # fmt: skip
    events = (await biz.owner.client.get(f"{biz.base}/audit-events")).json()["events"]
    assert any(e["action"] == "business_hours.updated" for e in events)


async def test_availability_api(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    r = await _set_availability(biz, mode="business_hours")
    assert r.status_code == 409 and r.json()["detail"] == "business_hours_not_set"
    r = await _set_availability(biz, paused_from=_iso(timedelta(0)))
    assert r.status_code == 422 and r.json()["detail"] == "invalid_pause"
    r = await _set_availability(
        biz, paused_from=_iso(timedelta(1)), paused_until=_iso(timedelta(0))
    )
    assert r.status_code == 422 and r.json()["detail"] == "invalid_pause"
    r = await _set_availability(biz, role="data_analyst")
    assert r.status_code == 422 and r.json()["detail"] == "invalid_role"
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    r = await member.client.put(f"{biz.agents}/sales/availability", json={"mode": "always"})
    assert r.status_code == 403

    await _set_hours(biz, CLOSED)
    r = await _set_availability(biz, mode="business_hours", away_message="We're closed.")
    assert r.status_code == 200, r.text
    sales = r.json()
    assert sales["availability"]["mode"] == "business_hours"
    assert sales["availability"]["away_message"] == "We're closed."
    assert sales["answering_now"] is False  # every day is closed
    agents = {a["role"]: a for a in (await biz.owner.client.get(biz.agents)).json()}
    assert agents["technical_support"]["availability"]["mode"] == "always"
    assert agents["technical_support"]["answering_now"] is True
    events = (await biz.owner.client.get(f"{biz.base}/audit-events")).json()["events"]
    assert any(e["action"] == "agent.availability_updated"
               and e["details"] == {"agent": "sales", "mode": "business_hours", "paused": False}
               for e in events)  # fmt: skip


# --- visitors -----------------------------------------------------------------------------------


async def test_paused_agent_sends_its_fixed_message_without_ai(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    r = await _set_availability(biz, paused_from=_iso(-timedelta(hours=1)),
                                paused_until=_iso(timedelta(days=2)),
                                pause_message="Eid Mubarak! We're back on Sunday.")  # fmt: skip
    assert r.status_code == 200 and r.json()["answering_now"] is False
    c, auth = await _visitor(harness, biz)
    calls = len(_fake(harness).calls)
    r = await _say(c, biz, auth, "Do you have chairs?", agent=SALES)
    body = r.json()
    assert r.status_code == 200 and body["reply"] == "Eid Mubarak! We're back on Sunday."
    assert body["agent"] == SALES and len(_fake(harness).calls) == calls  # no AI call
    # The visitor's message waits for the team in the Inbox.
    conv = body["conversation_id"]
    detail = (await biz.owner.client.get(f"{biz.base}/inbox/{conv}")).json()
    assert [m["content"] for m in detail["messages"]] == [
        "Do you have chairs?", "Eid Mubarak! We're back on Sunday."]  # fmt: skip

    # The test chat is not affected: the team can still try the agent.
    _fake(harness).replies.append("Yes, we do.")
    r = await biz.owner.client.post(f"{biz.agents}/sales/console", json={"message": "Chairs?"})
    assert r.json()["reply"] == "Yes, we do."

    # After the pause the AI answers again.
    await _set_availability(biz)
    _fake(harness).replies.append("We have three models.")
    r = await _say(c, biz, auth, "Which ones?", conv)
    assert r.json()["reply"] == "We have three models."


async def test_hours_modes_for_visitors(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    await _set_hours(biz, CLOSED)
    # During business hours only, and the business is closed: the default message.
    await _set_availability(biz, mode="business_hours")
    c, auth = await _visitor(harness, biz)
    r = await _say(c, biz, auth, "Hello?", agent=SALES)
    assert r.json()["reply"] == hours.DEFAULT_AWAY
    # Outside business hours only (covering the off time): it answers now.
    await _set_availability(biz, mode="outside_business_hours")
    _fake(harness).replies.append("Hi! How can I help?")
    r = await _say(c, biz, auth, "Hello again", r.json()["conversation_id"])
    assert r.json()["reply"] == "Hi! How can I help?"


async def test_away_messages_are_counted_apart_from_ai_replies(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    await _set_hours(biz, CLOSED)
    await _set_availability(biz, mode="business_hours")
    c, auth = await _visitor(harness, biz)
    await _say(c, biz, auth, "Anyone there?", agent=SALES)
    await analytics.compute_due(harness.app.state.session_factory)
    today = analytics.utc_today()
    s = (await biz.owner.client.get(f"{biz.base}/analytics/summary",
                                    params={"month": f"{today:%Y-%m}"})).json()  # fmt: skip
    totals = {m["name"]: m["value"] for m in s["totals"]}
    assert totals["away_replies"] == 1 and totals["ai_replies"] == 0
    assert totals["visitor_messages"] == 1


def test_default_business_week() -> None:
    from agentree.agents.config_api import DEFAULT_HOURS

    assert [d.start if d else None for d in DEFAULT_HOURS.days] == ["09:00"] * 5 + [None, None]
