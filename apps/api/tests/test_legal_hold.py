"""Task 21: Owner-only, audited legal hold that the retention purge respects; a persisted record
of every retention run; per-agent outcomes in the analytics."""

import pytest
from sqlalchemy import text

from agentree.analytics import service as analytics
from agentree.retention.service import purge_expired_conversations
from tests.conftest import AppHarness, DbUrls, _admin_execute
from tests.helpers import invite_and_join
from tests.test_agents import Biz, _fake, _say
from tests.test_analytics import _activity
from tests.test_support_agents import CS, SALES, _support_business, _visitor


async def _conversation(h: AppHarness, biz: Biz) -> str:
    c, auth = await _visitor(h, biz)
    _fake(h).replies.append("Hello!")
    return (await _say(c, biz, auth, "Hi", agent=SALES)).json()["conversation_id"]  # type: ignore[no-any-return]


async def _age(db_urls: DbUrls, conv: str, days: int = 40) -> None:
    """Make a conversation (and its messages) older than the retention window."""
    await _admin_execute(db_urls.admin, f"UPDATE conversation_messages SET created_at = now() - "
                         f"interval '{days} days' WHERE conversation_id = '{conv}'")  # fmt: skip
    await _admin_execute(db_urls.admin, f"UPDATE conversations SET created_at = now() - interval "
                         f"'{days} days', last_message_at = now() - interval '{days} days' "
                         f"WHERE id = '{conv}'")  # fmt: skip


# --- legal hold ---------------------------------------------------------------------------------


async def test_only_owners_place_a_hold_and_it_is_audited(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    conv = await _conversation(harness, biz)
    url = f"{biz.base}/inbox/{conv}/legal-hold"
    for role in ("admin", "member"):
        other = await invite_and_join(harness, biz.owner, biz.id, role)
        assert (await other.client.put(url, json={"held": True})).status_code == 403
    r = await biz.owner.client.put(url, json={"held": True})
    assert r.status_code == 200 and r.json() == {"held": True}
    detail = (await biz.owner.client.get(f"{biz.base}/inbox/{conv}")).json()
    assert detail["conversation"]["legal_hold"] is True
    items = (await biz.owner.client.get(f"{biz.base}/inbox")).json()["items"]
    assert [i["legal_hold"] for i in items if i["id"] == conv] == [True]
    await biz.owner.client.put(url, json={"held": True})  # no change: not audited again
    await biz.owner.client.put(url, json={"held": False})
    events = (await biz.owner.client.get(f"{biz.base}/audit-events")).json()["events"]
    holds = [e["details"]["held"] for e in events if e["action"] == "conversation.legal_hold"]
    assert sorted(holds) == [False, True]
    assert (await biz.owner.client.put(f"{biz.base}/inbox/{biz.id}/legal-hold",
                                       json={"held": True})).status_code == 404  # fmt: skip


async def test_retention_keeps_exactly_the_held_conversations(
    harness: AppHarness, db_urls: DbUrls
) -> None:
    biz = await _support_business(harness)
    held, other = await _conversation(harness, biz), await _conversation(harness, biz)
    await _age(db_urls, held)
    await _age(db_urls, other)
    await biz.owner.client.put(f"{biz.base}/inbox/{held}/legal-hold", json={"held": True})
    factory = harness.app.state.session_factory
    await purge_expired_conversations(factory, retention_days=30)
    assert (await biz.owner.client.get(f"{biz.base}/inbox/{held}")).status_code == 200
    assert (await biz.owner.client.get(f"{biz.base}/inbox/{other}")).status_code == 404
    # Released: deleted on the next pass.
    await biz.owner.client.put(f"{biz.base}/inbox/{held}/legal-hold", json={"held": False})
    await purge_expired_conversations(factory, retention_days=30)
    assert (await biz.owner.client.get(f"{biz.base}/inbox/{held}")).status_code == 404


# --- retention run records ----------------------------------------------------------------------


async def test_every_retention_run_leaves_a_record(harness: AppHarness, db_urls: DbUrls) -> None:
    biz = await _support_business(harness)
    conv = await _conversation(harness, biz)
    await _age(db_urls, conv)
    factory = harness.app.state.session_factory
    async with factory() as session:
        before = (await session.execute(text("SELECT count(*) FROM retention_runs"))).scalar_one()
    result = await purge_expired_conversations(factory, retention_days=30)
    async with factory() as session:
        row = (await session.execute(text(
            "SELECT rows_deleted, batches, cutoff < started_at, finished_at >= started_at "
            "FROM retention_runs ORDER BY id DESC LIMIT 1"))).one()  # fmt: skip
        after = (await session.execute(text("SELECT count(*) FROM retention_runs"))).scalar_one()
    assert after == before + 1
    assert row == (result.deleted, result.batches, True, True) and result.deleted >= 1
    info = (await biz.owner.client.get(f"{biz.base}/analytics/retention")).json()
    assert info["retention_days"] == 30 and info["last_run_at"] is not None


@pytest.mark.parametrize("sql", [
    "INSERT INTO retention_runs (started_at, finished_at, cutoff, rows_deleted, batches) "
    "VALUES (now(), now(), now(), 0, 0)",
    "UPDATE retention_runs SET rows_deleted = 0",
    "DELETE FROM retention_runs",
])  # fmt: skip
async def test_the_app_cannot_write_records_directly(harness: AppHarness, sql: str) -> None:
    with pytest.raises(Exception, match="permission denied"):
        async with harness.app.state.session_factory() as session, session.begin():
            await session.execute(text(sql))


@pytest.mark.parametrize("args", [
    "now(), now() - interval '1 hour', now() - interval '30 days', 0, 0",  # finished before start
    "now(), now(), now() + interval '1 day', 0, 0",  # cutoff after start
    "now(), now(), now() - interval '30 days', -1, 0",
    "now(), now() + interval '1 hour', now() - interval '30 days', 0, 0",  # in the future
])  # fmt: skip
async def test_bad_records_are_refused(harness: AppHarness, args: str) -> None:
    with pytest.raises(Exception, match="invalid retention run record"):
        async with harness.app.state.session_factory() as session, session.begin():
            await session.execute(text(f"SELECT agentree_record_retention_run({args})"))


# --- per-agent outcomes -------------------------------------------------------------------------


async def test_agent_outcomes_come_from_stored_activity(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    await _activity(harness, biz)  # Sales: 2 replies in 1 conversation; CS hands one to the team
    await analytics.compute_due(harness.app.state.session_factory)
    today = analytics.utc_today()
    s = (await biz.owner.client.get(f"{biz.base}/analytics/summary",
                                    params={"month": f"{today:%Y-%m}"})).json()  # fmt: skip
    agents = {a["role"]: a["outcomes"] for a in s["agents"]}
    assert agents[SALES] == {"conversations": 1, "replies": 2, "resolved": 0, "to_team": 0,
                             "handoffs_out": 0}  # fmt: skip
    assert agents[CS]["to_team"] == 1 and agents[CS]["replies"] == 1
    assert s["agent_outcome_labels"]["to_team"] == "Handed to your team"
    # Another business sees none of it.
    other = await _support_business(harness, name="Other Shop")
    s2 = (await other.owner.client.get(f"{other.base}/analytics/summary",
                                       params={"month": f"{today:%Y-%m}"})).json()  # fmt: skip
    assert s2["agents"] == []
