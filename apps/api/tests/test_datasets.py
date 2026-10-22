"""Uploaded tables (Task 18b): CSV/XLSX profiled in a sandbox, read-only SQL for the Data
Analyst only, checked numbers from query results, sandbox escapes refused, and isolation."""

import io
import uuid
import zipfile
from typing import Any

import pytest
from openpyxl import Workbook

from agentree.agents.service import QUERY_UNANSWERED, UNVERIFIED_NUMBERS
from agentree.knowledge import service as knowledge
from agentree.knowledge import tables
from agentree.tenancy.context import TenantContext, TenantSource
from tests.conftest import AppHarness
from tests.test_agents import Biz, _configure, _fake, _system
from tests.test_support_agents import _support_business

CSV = (
    b'region,amount,sold_on\nNorth,"1,000",2026-09-01\nSouth,700,2026-09-02\nNorth,500,2026-09-03\n'
)


def _xlsx(rows: list[list[Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


async def _upload(biz: Biz, name: str, data: bytes) -> dict[str, Any]:
    r = await biz.owner.client.post(f"{biz.base}/knowledge-files", files={"file": (name, data)})
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "processing"
    f = (await biz.owner.client.get(f"{biz.base}/knowledge-files/{r.json()['id']}")).json()
    return f  # type: ignore[no-any-return]


async def _analyst(biz: Biz, message: str, conv: str | None = None) -> dict[str, Any]:
    r = await biz.owner.client.post(f"{biz.base}/agents/sales/console", json={
        "message": message, "agent": "data_analyst", "conversation_id": conv})  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def _ctx(biz: Biz) -> TenantContext:
    return TenantContext(uuid.UUID(biz.id), TenantSource.JOB)


# --- profiling on upload ----------------------------------------------------------------------


async def test_tables_are_profiled_not_extracted(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    f = await _upload(biz, "sales.csv", CSV)
    assert f["status"] == "stored" and f["entry_count"] == 0, f
    assert f["table_rows"] == 3 and f["table_columns"] == ["region", "amount", "sold_on"]
    f = await _upload(biz, "Q3 Report.xlsx", _xlsx([["Product", "Units sold", "3rd"],
                                                     ["Chair", 12, 1.5], ["Desk", 4, None]]))  # fmt: skip
    assert f["status"] == "stored", f
    assert f["table_rows"] == 2 and f["table_columns"] == ["product", "units_sold", "c_3rd"]
    assert (await biz.owner.client.get(f"{biz.base}/knowledge")).json() == []
    # A workbook without sheets, or a file with no data rows, cannot be analysed.
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
    f = await _upload(biz, "q3.xlsx", empty.getvalue())
    assert f["status"] == "failed" and f["error"] == "damaged_file" and f["table_rows"] is None
    f = await _upload(biz, "header.csv", b"only,a,header\n")
    assert f["status"] == "failed" and f["error"] == "no_rows"


def test_cells_and_names_are_normalised() -> None:
    _names, types, rows = tables.load("csv", CSV)
    assert types == ["text", "integer", "text"]
    assert rows[0] == ["North", 1000, "2026-09-01"]
    assert tables._column_names(["", "a b", "a b", "١٢ x"]) == [
        "column_1",
        "a_b",
        "a_b_2",
        "c_١٢_x",
    ]


# --- the sandbox ------------------------------------------------------------------------------


def test_read_only_queries_work() -> None:
    out = tables.query("csv", CSV, "SELECT region, SUM(amount) AS total FROM data "
                                   "GROUP BY region ORDER BY region;")  # fmt: skip
    assert out == {"columns": ["region", "total"], "rows": [["North", 1500], ["South", 700]],
                   "truncated": False}  # fmt: skip
    many = b"n\n" + b"".join(f"{i}\n".encode() for i in range(300))
    out = tables.query("csv", many, "SELECT n FROM data")
    assert len(out["rows"]) == tables.MAX_RESULT_ROWS and out["truncated"]


@pytest.mark.parametrize(("sql", "code"), [
    ("SELECT name FROM sqlite_master", "query_failed"),
    ("SELECT * FROM data; DROP TABLE data", "invalid_sql"),
    ("DELETE FROM data", "invalid_sql"),
    ("PRAGMA table_info(data)", "invalid_sql"),
    ("ATTACH DATABASE '/tmp/x.db' AS x", "invalid_sql"),
    ("SELECT load_extension('/tmp/evil')", "query_failed"),
    ("SELECT readfile('/etc/passwd')", "query_failed"),
    ("SELECT randomblob(1000000000)", "query_failed"),
    ("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT max(n) FROM r",
     "query_failed"),
    ("WITH x AS (SELECT 1) INSERT INTO data SELECT * FROM x", "query_failed"),
    ("SELECT * FROM pragma_table_info('data')", "query_failed"),
    ("SELECT " + "1 + " * 3000 + "1", "invalid_sql"),
])  # fmt: skip
def test_sandbox_escapes_are_refused(sql: str, code: str) -> None:
    with pytest.raises(tables.TableError, match=code):
        tables.query("csv", CSV, sql)


def test_long_queries_are_stopped() -> None:
    big = b"n\n" + b"".join(f"{i}\n".encode() for i in range(400))
    with pytest.raises(tables.TableError, match="query_too_long"):
        tables.query("csv", big, "SELECT count(*) FROM data a, data b, data c, data d")


async def test_queries_run_in_the_limited_child(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    fid = (await _upload(biz, "sales.csv", CSV))["id"]
    factory = harness.app.state.session_factory
    result, error = await knowledge.query_dataset(factory, _ctx(biz), uuid.UUID(fid),
                                                  "SELECT COUNT(*) AS n FROM data")  # fmt: skip
    assert error is None and result is not None and result.rows == [[3]]
    result, error = await knowledge.query_dataset(factory, _ctx(biz), uuid.UUID(fid),
                                                  "SELECT * FROM sqlite_master")  # fmt: skip
    assert result is None and error == "query_failed"


# --- the Data Analyst -------------------------------------------------------------------------


async def test_analyst_answers_from_a_query_result(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    await _upload(biz, "sales_2025.csv", CSV)
    await _configure(biz, "data_analyst", enabled=True, public=False)
    _fake(harness).replies.extend([
        "<<SQL d1: SELECT region, SUM(amount) AS total FROM data GROUP BY region ORDER BY 1>>",
        "North sold 1,500 and South sold 700.",
    ])  # fmt: skip
    calls = len(_fake(harness).calls)
    body = await _analyst(biz, "Sales per region?")
    assert body["reply"] == "North sold 1,500 and South sold 700."
    assert len(_fake(harness).calls) == calls + 2
    first, second = _system(harness, -2), _system(harness, -1)
    assert "- d1: file sales_2025.csv; 3 rows; columns: region (text), amount (integer)" in first
    assert "<<SQL d1:" in first and "<<SQL d1:" not in second  # one query per turn
    assert "Query on d1: SELECT region" in second and "North | 1500\nSouth | 700" in second
    assert "<<SQL" not in body["reply"]

    # A result right after the row counts is checked as its own number (not glued to them).
    _fake(harness).replies.extend(["<<SQL d1: SELECT COUNT(*) AS n FROM data>>", "It has 3 rows."])
    assert (await _analyst(biz, "Rows?", body["conversation_id"]))["reply"] == "It has 3 rows."

    # Digits in a file name are not computed numbers; neither is an invented total.
    for invented in ("Your 2025 sales were great.", "Total sales: 2,900."):
        _fake(harness).replies.extend([
            "<<SQL d1: SELECT SUM(amount) AS total FROM data>>", invented])  # fmt: skip
        reply = (await _analyst(biz, "Total?", body["conversation_id"]))["reply"]
        assert reply.startswith(UNVERIFIED_NUMBERS) and "2,900" not in reply


async def test_failed_or_repeated_queries_never_reach_the_reply(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    await _upload(biz, "sales.csv", CSV)
    await _configure(biz, "data_analyst", enabled=True, public=False)
    _fake(harness).replies.extend(
        ["<<SQL d1: SELECT name FROM sqlite_master>>", "I couldn't compute that from the file."]
    )
    assert (await _analyst(biz, "Tables?"))["reply"] == "I couldn't compute that from the file."
    assert "Result: failed (query_failed). Do not guess" in _system(harness)
    _fake(harness).replies.extend([
        "<<SQL d9: SELECT 1 FROM data>>", "That table isn't there."])  # fmt: skip
    assert (await _analyst(biz, "d9?"))["reply"] == "That table isn't there."
    assert "Result: failed (no table with that label)" in _system(harness)
    # A second query in the same turn is not run; the reply falls back to computed numbers.
    _fake(harness).replies.extend([
        "<<SQL d1: SELECT 1 FROM data>>", "<<SQL d1: SELECT 2 FROM data>>"])  # fmt: skip
    reply = (await _analyst(biz, "Again?"))["reply"]
    assert reply.startswith(QUERY_UNANSWERED) and "<<SQL" not in reply


async def test_only_the_analyst_queries_and_only_its_own_tables(harness: AppHarness) -> None:
    a = await _support_business(harness)
    b = await _support_business(harness, name="Other Shop")
    b_file = (await _upload(b, "b_sales.csv", CSV))["id"]
    await _configure(a, "data_analyst", enabled=True, public=False)
    _fake(harness).replies.append("No uploaded tables yet.")
    await _analyst(a, "What tables do I have?")
    system = _system(harness)
    assert "b_sales" not in system and "Uploaded tables" not in system and "<<SQL" not in system
    factory = harness.app.state.session_factory
    assert await knowledge.datasets(factory, _ctx(a)) == []
    assert await knowledge.query_dataset(factory, _ctx(a), uuid.UUID(b_file), "SELECT 1") == (
        None, "not_found")  # fmt: skip
    # Other agents never get the tables or the query instruction.
    await _upload(a, "a_sales.csv", CSV)
    _fake(harness).replies.append("Hello!")
    r = await a.owner.client.post(f"{a.base}/agents/sales/console", json={"message": "Hi"})
    assert r.status_code == 200
    assert "a_sales" not in _system(harness) and "<<SQL" not in _system(harness)
