"""BYOK provider credential API: storage encryption, write-only keys, roles, isolation."""

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agentree.llm.base import ErrorKind, ProviderName
from agentree.providers import service
from agentree.tenancy.context import TenantContext, TenantSource
from tests.conftest import AppHarness
from tests.helpers import Account, create_business, invite_and_join, signup

SECRET = "sk-live-VERYSECRET-9f8e7d6c5b4a"  # noqa: S105  # gitleaks:allow (fake test key)


def _body(**over: object) -> dict[str, object]:
    return {"provider": "openai", "model": "gpt-4o-mini", "api_key": SECRET, "verify": True} | over


async def _setup(harness: AppHarness) -> tuple[Account, str]:
    owner = await signup(harness)
    biz = await create_business(owner)
    return owner, f"/api/businesses/{biz['id']}/ai-providers"


async def test_save_list_and_key_is_never_returned(
    harness: AppHarness, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    owner, base = await _setup(harness)
    r = await owner.client.put(f"{base}/primary", json=_body())
    assert r.status_code == 200, r.text
    assert SECRET not in r.text
    assert r.json()["key_hint"] == "5b4a" and r.json()["last_verified_at"] is not None
    listed = await owner.client.get(base)
    assert SECRET not in listed.text
    assert [c["slot"] for c in listed.json()] == ["primary"]
    # verification call used the submitted key
    api_key, _ = harness.llm[ProviderName.OPENAI].calls[-1]
    assert api_key == SECRET
    assert SECRET not in caplog.text


async def test_database_holds_only_ciphertext(
    harness: AppHarness, migrator_engine: AsyncEngine
) -> None:
    owner, base = await _setup(harness)
    await owner.client.put(f"{base}/primary", json=_body())
    async with migrator_engine.connect() as conn:
        rows = (await conn.execute(text("SELECT * FROM provider_credentials"))).mappings().all()
    dump = repr([dict(r) for r in rows]).encode()
    assert SECRET.encode() not in dump and b"VERYSECRET" not in dump


async def test_rejected_key_is_not_saved(harness: AppHarness) -> None:
    owner, base = await _setup(harness)
    harness.llm[ProviderName.ANTHROPIC].valid_keys = {"some-other-key-000"}
    r = await owner.client.put(f"{base}/primary", json=_body(provider="anthropic"))
    assert r.status_code == 422 and r.json()["detail"] == "key_rejected"
    assert (await owner.client.get(base)).json() == []


async def test_provider_outage_during_verify_is_502_and_not_saved(harness: AppHarness) -> None:
    owner, base = await _setup(harness)
    harness.llm[ProviderName.GEMINI].replies.append(ErrorKind.UNAVAILABLE)
    r = await owner.client.put(
        f"{base}/backup", json=_body(provider="gemini", model="gemini-2.0-flash")
    )
    assert r.status_code == 502
    assert (await owner.client.get(base)).json() == []


async def test_save_without_verify_skips_provider_call(harness: AppHarness) -> None:
    owner, base = await _setup(harness)
    r = await owner.client.put(f"{base}/backup", json=_body(verify=False))
    assert r.status_code == 200 and r.json()["last_verified_at"] is None
    assert harness.llm[ProviderName.OPENAI].calls == []


async def test_replace_and_delete_slot(harness: AppHarness) -> None:
    owner, base = await _setup(harness)
    await owner.client.put(f"{base}/primary", json=_body())
    r = await owner.client.put(f"{base}/primary", json=_body(api_key="sk-new-key-000000ZZZZ"))
    assert r.json()["key_hint"] == "ZZZZ"
    assert len((await owner.client.get(base)).json()) == 1
    assert (await owner.client.delete(f"{base}/primary")).status_code == 204
    assert (await owner.client.delete(f"{base}/primary")).status_code == 404


async def test_test_endpoint_uses_decrypted_key_and_records_result(harness: AppHarness) -> None:
    owner, base = await _setup(harness)
    await owner.client.put(f"{base}/primary", json=_body(verify=False))
    r = await owner.client.post(f"{base}/primary/test")
    assert r.json() == {"ok": True, "error_kind": None}
    assert harness.llm[ProviderName.OPENAI].calls[-1][0] == SECRET
    harness.llm[ProviderName.OPENAI].replies.append(ErrorKind.QUOTA)
    r = await owner.client.post(f"{base}/primary/test")
    assert r.json() == {"ok": False, "error_kind": "quota"}
    assert (await owner.client.get(base)).json()[0]["last_error_kind"] == "quota"


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        (_body(provider="mistral"), None),  # schema-level 422
        (_body(model="../etc"), "invalid_model"),
        (_body(api_key="has spaces in key"), "invalid_api_key_format"),
    ],
)
async def test_invalid_input_rejected(
    harness: AppHarness, body: dict[str, object], detail: str | None
) -> None:
    owner, base = await _setup(harness)
    r = await owner.client.put(f"{base}/primary", json=body)
    assert r.status_code == 422
    if detail:
        assert r.json()["detail"] == detail
    assert SECRET not in r.text


async def test_members_can_view_but_not_change_keys(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    base = f"/api/businesses/{biz['id']}/ai-providers"
    await owner.client.put(f"{base}/primary", json=_body())
    member = await invite_and_join(harness, owner, biz["id"], "member")
    assert (await member.client.get(base)).status_code == 200
    assert (await member.client.put(f"{base}/backup", json=_body())).status_code == 403
    assert (await member.client.delete(f"{base}/primary")).status_code == 403
    assert (await member.client.post(f"{base}/primary/test")).status_code == 403


async def test_admin_can_manage_keys(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    admin = await invite_and_join(harness, owner, biz["id"], "admin")
    r = await admin.client.put(f"/api/businesses/{biz['id']}/ai-providers/backup", json=_body())
    assert r.status_code == 200


async def test_ciphertext_moved_to_another_business_cannot_be_decrypted(
    harness: AppHarness, migrator_engine: AsyncEngine
) -> None:
    alice, base_a = await _setup(harness)
    bob, base_b = await _setup(harness)
    await alice.client.put(f"{base_a}/primary", json=_body())
    await bob.client.put(f"{base_b}/primary", json=_body(api_key="sk-bob-key-0000000000"))
    a_id = base_a.split("/")[3]
    b_id = base_b.split("/")[3]
    # Simulate a DB-level attack/bug: copy Alice's sealed key into Bob's row.
    async with migrator_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE provider_credentials b SET ciphertext = a.ciphertext, wrapped_dek = a.wrapped_dek "
                "FROM provider_credentials a WHERE a.business_id = :a AND b.business_id = :b"
            ),
            {"a": a_id, "b": b_id},
        )
    r = await bob.client.post(f"{base_b}/primary/test")
    assert r.status_code == 409 and r.json()["detail"] == "key_unreadable_reenter"
    assert SECRET not in [c[0] for c in harness.llm[ProviderName.OPENAI].calls[-1:]]


async def test_vault_unavailable_without_master_key(harness: AppHarness) -> None:
    owner, base = await _setup(harness)
    vault = harness.app.state.vault
    harness.app.state.vault = None
    try:
        r = await owner.client.put(f"{base}/primary", json=_body(verify=False))
        assert r.status_code == 503 and r.json()["detail"] == "key_vault_unavailable"
    finally:
        harness.app.state.vault = vault


async def test_resolve_rewraps_to_active_master_key(
    harness: AppHarness, migrator_engine: AsyncEngine
) -> None:
    owner, base = await _setup(harness)
    await owner.client.put(f"{base}/primary", json=_body(verify=False))
    business_id = base.split("/")[3]
    from uuid import UUID

    from agentree.core.vault import Vault, generate_master_key, parse_master_key

    old: Vault = harness.app.state.vault
    new = Vault("k2", {"k2": parse_master_key(generate_master_key()), **old._keys})
    ctx = TenantContext(UUID(business_id), TenantSource.MEMBERSHIP)
    factory = harness.app.state.session_factory
    cred = await service.resolve_credential(factory, new, ctx, service.Slot.PRIMARY)
    assert cred.api_key == SECRET
    async with migrator_engine.connect() as conn:
        kid = (
            await conn.execute(
                text("SELECT master_key_id FROM provider_credentials WHERE business_id = :b"),
                {"b": business_id},
            )
        ).scalar_one()
    assert kid == "k2"
