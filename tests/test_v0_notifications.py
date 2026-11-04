"""Offline inbox/delivery oracles; no real token, account or external message."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import TypeVar, cast

import pytest

from quant_hunter.notifications.store import NotificationStore
from quant_hunter.notifications.telegram import (
    FixedTelegramHTTPS,
    TelegramResult,
    TelegramService,
    WireRequest,
    normalize_response,
)
from quant_hunter.notifications.types import (
    Notification,
    NotificationError,
    SendAuthorization,
    TelegramConfig,
    TelegramPolicy,
    VaultReference,
    canonical,
    digest,
    message_payload,
    telegram_profile_schema,
)

NOW = datetime(2026, 10, 5, tzinfo=UTC)
TOKEN = "123456789:" + "SyntheticFixtureOnly_12345"
T = TypeVar("T")


def event(number: int = 1) -> Notification:
    return Notification(
        f"N-{number}",
        f"D-{number}",
        "TEST",
        "INFO",
        "SYNTHETIC",
        "Local diagnostic",
        "No market observation or broker action.",
        NOW,
        NOW + timedelta(hours=1),
        "EXP-EXISTING",
    )


def config(owner: str = "OWNER", revision: int = 1) -> TelegramConfig:
    return TelegramConfig(
        owner,
        revision,
        VaultReference("TELEGRAM", "owner_fixture", "configuration"),
        "-123456789",
        True,
    )


def permit(
    item: Notification, target: TelegramConfig, number: int = 1, now: datetime = NOW
) -> SendAuthorization:
    return SendAuthorization(
        f"AUTH-{number}",
        target.owner_id,
        digest(item.payload),
        digest(target.payload),
        digest(message_payload(target, item)),
        "EXPLICIT_TEST",
        now,
        now + timedelta(seconds=30),
    )


class FakeVault:
    def __init__(self) -> None:
        self.raw = json.dumps(
            {"bot_token": TOKEN, "allowed_chat_id": config().chat_id}
        ).encode()
        self.calls = 0
        self.error: Exception | None = None

    def with_secret(
        self, provider: str, account: str, slot: str, consumer: Callable[[bytes], T]
    ) -> T:
        self.calls += 1
        assert (provider, account, slot) == (
            "TELEGRAM",
            "owner_fixture",
            "configuration",
        )
        if self.error is not None:
            raise self.error
        return consumer(self.raw)


class FakeTelegram:
    def __init__(self) -> None:
        self.calls: list[WireRequest] = []
        self.result = TelegramResult("SENT", "TELEGRAM_ACKNOWLEDGED", 77)
        self.error: Exception | None = None

    def send(self, request: WireRequest) -> TelegramResult:
        request.validate(NOW)
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def setup(
    tmp_path: Path,
) -> tuple[NotificationStore, TelegramService, FakeVault, FakeTelegram]:
    store = NotificationStore(tmp_path / "app.sqlite")
    store.publish("OWNER", event(), now=NOW)
    store.configure("OWNER", config(), expected_revision=0, now=NOW)
    vault, transport = FakeVault(), FakeTelegram()
    service = TelegramService(
        store,
        vault,
        policy=TelegramPolicy.REVIEWED_V0_TOKEN_PATH,
        transport=transport,
        clock=lambda: NOW,
    )
    return store, service, vault, transport


def test_local_inbox_runs_without_any_external_configuration_and_survives_restart(
    tmp_path: Path,
) -> None:
    store = NotificationStore(tmp_path / "app.sqlite")
    first = store.publish("OWNER", event(), now=NOW)
    assert first.local_status == "DELIVERED_LOCAL" and first.event.mode == "SYNTHETIC"
    assert (
        store.configuration("OWNER") is None and store.delivery("OWNER", "N-1") is None
    )
    assert store.publish("OWNER", event(), now=NOW) == first
    restarted = NotificationStore(tmp_path / "app.sqlite")
    assert restarted.inbox("OWNER") == (first,)
    read = restarted.mark_read("OWNER", "N-1", now=NOW + timedelta(seconds=1))
    assert read.read_at is not None
    assert restarted.mark_read("OWNER", "N-1", now=NOW + timedelta(seconds=2)) == read
    assert len(restarted.audit("OWNER")) == 2


def test_additive_tables_preserve_existing_application_data_and_backup(
    tmp_path: Path,
) -> None:
    path = tmp_path / "app.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE application_users(id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO application_users VALUES('existing')")
        db.commit()
    store = NotificationStore(path)
    store.publish("OWNER", event(), now=NOW)
    with (
        closing(sqlite3.connect(path)) as db,
        closing(sqlite3.connect(tmp_path / "backup.sqlite")) as backup,
    ):
        db.backup(backup)
        assert (
            backup.execute("SELECT id FROM application_users").fetchone()[0]
            == "existing"
        )
    assert (
        NotificationStore(tmp_path / "backup.sqlite").get("OWNER", "N-1").event
        == event()
    )


@pytest.mark.parametrize("operation", ["get", "read", "delivery", "send", "configure"])
def test_cross_owner_access_fails_without_disclosing_event(
    tmp_path: Path, operation: str
) -> None:
    store, service, _, transport = setup(tmp_path)
    with pytest.raises(NotificationError):
        if operation == "get":
            store.get("OTHER", "N-1")
        elif operation == "read":
            store.mark_read("OTHER", "N-1", now=NOW)
        elif operation == "delivery":
            store.delivery("OTHER", "N-1")
        elif operation == "configure":
            store.configure("OTHER", config(), expected_revision=0, now=NOW)
        else:
            service.send("OTHER", "N-1", permit(event(), config()))
    assert store.inbox("OTHER") == () and store.audit("OTHER") == ()
    assert not transport.calls


@pytest.mark.parametrize(
    "change",
    [{"body": "changed"}, {"notification_id": "N-2"}, {"dedupe_key": "different"}],
)
def test_dedupe_conflicts_do_not_overwrite_existing_work(
    tmp_path: Path, change: dict[str, object]
) -> None:
    store = NotificationStore(tmp_path / "app.sqlite")
    store.publish("OWNER", event(), now=NOW)
    with pytest.raises(NotificationError, match="CONFLICTING"):
        store.publish("OWNER", replace(event(), **change), now=NOW)  # type: ignore[arg-type]
    assert store.get("OWNER", "N-1").event == event()


def test_local_rate_and_expiry_are_visible_and_retained(tmp_path: Path) -> None:
    store = NotificationStore(tmp_path / "app.sqlite")
    for i in range(30):
        assert (
            store.publish("OWNER", event(i), now=NOW).local_status == "DELIVERED_LOCAL"
        )
    assert store.publish("OWNER", event(31), now=NOW).local_status == "RATE_LIMITED"
    assert (
        store.publish("OWNER", event(32), now=NOW + timedelta(hours=2)).local_status
        == "EXPIRED"
    )
    assert len(store.inbox("OWNER")) == 32


def test_clock_rollback_or_transaction_fault_leaves_no_partial_event(
    tmp_path: Path,
) -> None:
    store = NotificationStore(tmp_path / "app.sqlite")
    store.publish("OWNER", event(), now=NOW + timedelta(seconds=1))
    with pytest.raises(NotificationError, match="CLOCK"):
        store.publish("OWNER", event(2), now=NOW)

    def fail() -> None:
        raise RuntimeError("injected transaction failure")

    faulty = NotificationStore(tmp_path / "app.sqlite", before_commit=fail)
    with pytest.raises(RuntimeError, match="injected"):
        faulty.publish("OWNER", event(3), now=NOW + timedelta(seconds=2))
    assert len(store.inbox("OWNER")) == 1 and len(store.audit("OWNER")) == 1


def test_configuration_cas_disable_and_history_are_durable(tmp_path: Path) -> None:
    store, _, _, _ = setup(tmp_path)
    with pytest.raises(NotificationError, match="STALE"):
        store.configure("OWNER", config(), expected_revision=0, now=NOW)
    disabled = replace(config(revision=2), enabled=False)
    store.configure("OWNER", disabled, expected_revision=1, now=NOW)
    assert NotificationStore(tmp_path / "app.sqlite").configuration("OWNER") == disabled
    with closing(sqlite3.connect(tmp_path / "app.sqlite")) as db:
        assert db.execute("SELECT count(*) FROM qhn_configs").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM qhn_configs")


def test_explicit_send_retains_safe_receipt_never_credential_or_raw_provider_data(
    tmp_path: Path,
) -> None:
    store, service, vault, transport = setup(tmp_path)
    result = service.send("OWNER", "N-1", permit(event(), config()))
    assert result.state == "SENT" and result.message_id == 77
    assert vault.calls == 1 and len(transport.calls) == 1
    assert TOKEN not in repr(transport.calls)
    assert TOKEN.encode() not in (tmp_path / "app.sqlite").read_bytes()
    assert TOKEN not in repr(store.audit("OWNER"))
    assert service.send("OWNER", "N-1", permit(event(), config(), 2)) == result
    assert len(transport.calls) == 1


@pytest.mark.parametrize("failure", ["timeout", "vault", "malformed_result"])
def test_unknown_send_is_not_repeated_after_restart_or_new_authorization(
    tmp_path: Path, failure: str
) -> None:
    _store, service, vault, transport = setup(tmp_path)
    if failure == "timeout":
        transport.error = TimeoutError(TOKEN)
    elif failure == "vault":
        vault.error = ValueError(TOKEN)
    else:
        transport.result = TelegramResult("SENT", "LEAK_" + TOKEN, 77)
    result = service.send("OWNER", "N-1", permit(event(), config()))
    assert result.state == "UNKNOWN" and TOKEN not in repr(result)
    restarted = TelegramService(
        NotificationStore(tmp_path / "app.sqlite"),
        vault,
        policy=TelegramPolicy.REVIEWED_V0_TOKEN_PATH,
        transport=transport,
        clock=lambda: NOW,
    )
    calls = (vault.calls, len(transport.calls))
    assert restarted.send("OWNER", "N-1", permit(event(), config(), 2)) == result
    assert calls == (vault.calls, len(transport.calls))


def test_crash_after_reservation_and_reconfiguration_cannot_retarget_or_resend(
    tmp_path: Path,
) -> None:
    store, service, vault, transport = setup(tmp_path)
    fresh, unknown = store.reserve_send(
        "OWNER", "N-1", permit(event(), config()), now=NOW
    )
    assert fresh and unknown.state == "UNKNOWN"
    changed = replace(config(revision=2), chat_id="999")
    store.configure("OWNER", changed, expected_revision=1, now=NOW)
    result = service.send("OWNER", "N-1", permit(event(), changed, 2))
    assert result == unknown and result.configuration_digest == digest(config().payload)
    assert not transport.calls and vault.calls == 0


def test_competing_workers_reserve_exactly_one_delivery(tmp_path: Path) -> None:
    store, _, vault, transport = setup(tmp_path)
    barrier = Barrier(2)

    def send() -> str:
        service = TelegramService(
            NotificationStore(tmp_path / "app.sqlite"),
            vault,
            policy=TelegramPolicy.REVIEWED_V0_TOKEN_PATH,
            transport=transport,
            clock=lambda: NOW,
        )
        barrier.wait(timeout=5)
        return service.send("OWNER", "N-1", permit(event(), config())).state

    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = pool.submit(send), pool.submit(send)
        statuses = {left.result(), right.result()}
    assert "SENT" in statuses and statuses <= {"SENT", "UNKNOWN"}
    assert len(transport.calls) == 1 and vault.calls == 1
    assert store.delivery("OWNER", "N-1") is not None


def test_telegram_rate_gate_is_atomic_and_local_event_remains_visible(
    tmp_path: Path,
) -> None:
    store, service, vault, transport = setup(tmp_path)
    service.send("OWNER", "N-1", permit(event(), config()))
    store.publish("OWNER", event(2), now=NOW)
    result = service.send("OWNER", "N-2", permit(event(2), config(), 2))
    assert (
        result.state == "RATE_LIMITED"
        and len(transport.calls) == 1
        and vault.calls == 1
    )
    assert store.get("OWNER", "N-2").local_status == "DELIVERED_LOCAL"


@pytest.mark.parametrize(
    "fault",
    ["owner", "event", "config", "request", "expired", "future", "long", "purpose"],
)
def test_authorization_must_bind_exact_event_target_and_time(
    tmp_path: Path, fault: str
) -> None:
    store, service, vault, transport = setup(tmp_path)
    auth = permit(event(), config())
    if fault == "owner":
        auth = replace(auth, owner_id="OTHER")
    elif fault == "event":
        auth = replace(auth, notification_digest="sha256:" + "0" * 64)
    elif fault == "config":
        auth = replace(auth, configuration_digest="sha256:" + "0" * 64)
    elif fault == "request":
        auth = replace(auth, request_digest="sha256:" + "0" * 64)
    elif fault == "expired":
        auth = replace(auth, approved_at=NOW - timedelta(seconds=31), expires_at=NOW)
    elif fault == "future":
        auth = replace(auth, approved_at=NOW + timedelta(seconds=1))
    elif fault == "long":
        auth = replace(auth, expires_at=NOW + timedelta(seconds=31))
    else:
        auth = replace(auth, purpose="AUTOMATIC")
    with pytest.raises(NotificationError):
        service.send("OWNER", "N-1", auth)
    assert (
        vault.calls == 0
        and not transport.calls
        and store.delivery("OWNER", "N-1") is None
    )


@pytest.mark.parametrize(
    "policy",
    [
        TelegramPolicy.DISABLED,
        "arbitrary-decision",
        TelegramPolicy.REVIEWED_V0_TOKEN_PATH.value,
    ],
)
def test_policy_is_a_typed_host_capability_not_an_exception_string(
    tmp_path: Path, policy: object
) -> None:
    store, _, vault, transport = setup(tmp_path)
    service = TelegramService(
        store,
        vault,
        policy=cast(TelegramPolicy, policy),
        transport=transport,
        clock=lambda: NOW,
    )
    with pytest.raises(NotificationError, match="POLICY"):
        service.send("OWNER", "N-1", permit(event(), config()))
    assert not transport.calls and vault.calls == 0


@pytest.mark.parametrize(
    "change",
    [
        {"title": ""},
        {"body": TOKEN},
        {"body": "secret=hidden"},
        {"body": "https://example.com/key"},
        {"body": "x" * 2001},
        {"body": "bad\x00text"},
        {"body": "\ud800"},
        {"mode": "LIVE"},
        {"severity": "PROFITABLE"},
        {"kind": "UNKNOWN"},
        {"experiment_id": "STR-X"},
        {"created_at": NOW.replace(tzinfo=None)},
        {"expires_at": NOW},
        {"expires_at": NOW + timedelta(days=8)},
        {"notification_id": "../escape"},
    ],
)
def test_closed_event_contract_rejects_secret_or_invalid_payloads(
    change: dict[str, object],
) -> None:
    with pytest.raises(NotificationError):
        replace(event(), **change).validate()  # type: ignore[arg-type]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429])
def test_documented_telegram_error_responses_are_safe_refusals(status: int) -> None:
    request = WireRequest(
        TOKEN,
        config(),
        event(),
        permit(event(), config()),
        TelegramPolicy.REVIEWED_V0_TOKEN_PATH,
    )
    result = normalize_response(
        status,
        json.dumps(
            {"ok": False, "description": "provider private description"}
        ).encode(),
        request,
    )
    assert result.state == "REJECTED" and "private" not in repr(result)


@pytest.mark.parametrize(
    "fault",
    [
        "bad_json",
        "duplicate",
        "huge",
        "wrong_chat",
        "wrong_text",
        "missing_message",
        "plain_secret",
        "escaped_secret",
        "server_error",
        "redirect",
    ],
)
def test_http_schema_and_reflection_fail_without_retaining_raw_response(
    fault: str,
) -> None:
    request = WireRequest(
        TOKEN,
        config(),
        event(),
        permit(event(), config()),
        TelegramPolicy.REVIEWED_V0_TOKEN_PATH,
    )
    value: dict[str, object] = {
        "ok": True,
        "result": {
            "message_id": 77,
            "chat": {"id": int(config().chat_id)},
            "text": event().telegram_text,
        },
    }
    status, raw = 200, json.dumps(value).encode()
    if fault == "bad_json":
        raw = b"bad"
    elif fault == "duplicate":
        raw = b'{"ok":true,"ok":false}'
    elif fault == "huge":
        raw = b"x" * 65537
    elif fault in ("wrong_chat", "wrong_text", "missing_message"):
        result = cast(dict[str, object], value["result"])
        if fault == "wrong_chat":
            result["chat"] = {"id": 999}
        elif fault == "wrong_text":
            result["text"] = "different"
        else:
            result.pop("message_id")
        raw = json.dumps(value).encode()
    elif fault == "plain_secret":
        raw = json.dumps({"ok": False, "description": TOKEN}).encode()
    elif fault == "escaped_secret":
        raw = (
            '{"ok":false,"description":"'
            + "".join(f"\\u{ord(c):04x}" for c in TOKEN)
            + '"}'
        ).encode()
    elif fault == "server_error":
        status = 500
    else:
        status = 302
    with pytest.raises(NotificationError) as captured:
        normalize_response(status, raw, request)
    assert TOKEN not in str(captured.value)


def test_positive_telegram_normalization_and_default_network_block() -> None:
    now = datetime.now(UTC)
    item = replace(event(), created_at=now, expires_at=now + timedelta(hours=1))
    request = WireRequest(
        TOKEN,
        config(),
        item,
        permit(item, config(), now=now),
        TelegramPolicy.REVIEWED_V0_TOKEN_PATH,
    )
    raw = json.dumps(
        {
            "ok": True,
            "result": {
                "message_id": 77,
                "chat": {"id": int(config().chat_id)},
                "text": item.telegram_text,
            },
        }
    ).encode()
    assert normalize_response(200, raw, request) == TelegramResult(
        "SENT", "TELEGRAM_ACKNOWLEDGED", 77
    )
    assert FixedTelegramHTTPS().send(request).state == "BLOCKED"
    profile = telegram_profile_schema()
    assert profile["additionalProperties"] is False
    assert TOKEN not in json.dumps(profile)
    assert digest(canonical(profile)).startswith("sha256:")


@pytest.mark.parametrize(
    "change",
    [
        {"owner_id": "../x"},
        {"revision": 0},
        {"revision": True},
        {"enabled": 1},
        {"chat_id": "@anybody"},
        {"chat_id": "0"},
        {"chat_id": "4503599627370496"},
        {"vault": VaultReference("OTHER", "owner", "slot")},
        {"vault": VaultReference("TELEGRAM", "../x", "slot")},
    ],
)
def test_configuration_rejects_arbitrary_target_or_credential_slot(
    change: dict[str, object],
) -> None:
    with pytest.raises(NotificationError):
        replace(config(), **change).validate()  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "case",
    ["disabled", "expired", "local_limited", "vault_mismatch", "default_transport"],
)
def test_delivery_blockers_preserve_the_local_inbox(tmp_path: Path, case: str) -> None:
    store, service, vault, transport = setup(tmp_path)
    target, item, now = config(), event(), NOW
    if case == "disabled":
        target = replace(config(revision=2), enabled=False)
        store.configure("OWNER", target, expected_revision=1, now=NOW)
    elif case == "expired":
        now = NOW + timedelta(hours=2)
        service.clock = lambda: now
    elif case == "local_limited":
        for i in range(2, 32):
            store.publish("OWNER", event(i), now=NOW)
        item = event(31)
    elif case == "vault_mismatch":
        vault.raw = json.dumps({"bot_token": TOKEN, "allowed_chat_id": "999"}).encode()
    else:
        service = TelegramService(
            store,
            vault,
            policy=TelegramPolicy.REVIEWED_V0_TOKEN_PATH,
            clock=lambda: NOW,
        )
    result = service.send("OWNER", item.notification_id, permit(item, target, now=now))
    assert result.state in {"BLOCKED", "EXPIRED"} and not transport.calls
    assert store.get("OWNER", item.notification_id).event == item


def test_no_configuration_and_non_test_event_are_rejected_before_vault_use(
    tmp_path: Path,
) -> None:
    store = NotificationStore(tmp_path / "app.sqlite")
    item = replace(event(), kind="RISK")
    store.publish("OWNER", item, now=NOW)
    vault = FakeVault()
    service = TelegramService(
        store, vault, policy=TelegramPolicy.REVIEWED_V0_TOKEN_PATH, clock=lambda: NOW
    )
    with pytest.raises(NotificationError, match="NOT_CONFIGURED"):
        service.send("OWNER", "N-1", permit(item, config()))
    store.configure("OWNER", config(), expected_revision=0, now=NOW)
    with pytest.raises(NotificationError, match="TEST_EVENT"):
        service.send("OWNER", "N-1", permit(item, config()))
    assert vault.calls == 0


@pytest.mark.parametrize("kind", ["event", "config", "attempt", "receipt", "audit"])
def test_persisted_corruption_is_detected_without_overwriting_history(
    tmp_path: Path, kind: str
) -> None:
    store, service, _, _ = setup(tmp_path)
    service.send("OWNER", "N-1", permit(event(), config()))
    tables = {
        "event": ("qhn_events", "payload"),
        "config": ("qhn_configs", "payload"),
        "attempt": ("qhn_attempts", "authorization"),
        "receipt": ("qhn_receipts", "reason"),
        "audit": ("qhn_audit", "event_hash"),
    }
    table, column = tables[kind]
    with closing(sqlite3.connect(tmp_path / "app.sqlite")) as db:
        db.execute(f"DROP TRIGGER {table}_UPDATE")
        db.execute(f"UPDATE {table} SET {column}=?", ("corrupted",))  # noqa: S608 - fixed hostile-test table/column map
        db.commit()
    with pytest.raises(NotificationError, match="INTEGRITY"):
        if kind == "event":
            store.get("OWNER", "N-1")
        elif kind == "config":
            store.configuration("OWNER")
        elif kind == "audit":
            store.audit("OWNER")
        else:
            store.delivery("OWNER", "N-1")


@pytest.mark.parametrize(
    "args", [{"after": -1}, {"limit": 0}, {"limit": 101}, {"after": True}]
)
def test_inbox_query_limits_are_closed(tmp_path: Path, args: dict[str, int]) -> None:
    store = NotificationStore(tmp_path / "app.sqlite")
    with pytest.raises(NotificationError, match="PAGE_BOUND"):
        store.inbox("OWNER", **args)
    with pytest.raises(NotificationError, match="PAGE_BOUND"):
        store.audit("OWNER", limit=101)


def test_future_event_and_oversized_encoded_unicode_are_refused(tmp_path: Path) -> None:
    store = NotificationStore(tmp_path / "app.sqlite")
    with pytest.raises(NotificationError, match="FUTURE"):
        store.publish(
            "OWNER", replace(event(), created_at=NOW + timedelta(seconds=1)), now=NOW
        )
    with pytest.raises(NotificationError, match="PAYLOAD_LIMIT"):
        store.publish("OWNER", replace(event(), body="😀" * 1900), now=NOW)


def test_delivery_result_is_idempotent_but_cannot_change_a_recorded_outcome(
    tmp_path: Path,
) -> None:
    store, service, _, _ = setup(tmp_path)
    result = service.send("OWNER", "N-1", permit(event(), config()))
    assert (
        store.finish_send(
            "OWNER", "N-1", "SENT", "TELEGRAM_ACKNOWLEDGED", message_id=77, now=NOW
        )
        == result
    )
    with pytest.raises(NotificationError, match="FINALIZED"):
        store.finish_send("OWNER", "N-1", "UNKNOWN", "CHANGED", now=NOW)
    with pytest.raises(NotificationError, match="INVALID_DELIVERY"):
        store.finish_send("OWNER", "N-1", "SENT", "X", now=NOW)
    with pytest.raises(NotificationError, match="NOT_FOUND"):
        store.finish_send("OTHER", "N-1", "UNKNOWN", "X", now=NOW)


def test_authorization_id_is_not_reusable_for_another_event(tmp_path: Path) -> None:
    store, service, _, _ = setup(tmp_path)
    service.send("OWNER", "N-1", permit(event(), config()))
    store.publish("OWNER", event(2), now=NOW)
    with pytest.raises(NotificationError, match="AUTHORIZATION_ALREADY_USED"):
        service.send("OWNER", "N-2", permit(event(2), config()))
    assert store.delivery("OWNER", "N-2") is None


@pytest.mark.parametrize("phase", ["before_vault", "during_vault"])
def test_reconfiguration_before_wire_cannot_silently_redirect_a_pending_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    store, service, vault, transport = setup(tmp_path)
    reads = 0

    def current(owner: str) -> TelegramConfig:
        nonlocal reads
        reads += 1
        if phase == "before_vault" or reads > 1:
            return replace(config(revision=2), chat_id="999")
        return config()

    monkeypatch.setattr(store, "configuration", current)
    result = service.send("OWNER", "N-1", permit(event(), config()))
    assert result.state == "BLOCKED" and not transport.calls
    assert result.configuration_digest == digest(config().payload)
    assert vault.calls == (0 if phase == "before_vault" else 1)


@pytest.mark.parametrize("fault", ["invalid_token", "disabled", "non_test"])
def test_wire_contract_independently_checks_secret_shape_configuration_and_purpose(
    fault: str,
) -> None:
    item, target = event(), config()
    token = TOKEN
    if fault == "invalid_token":
        token = "not-a-token"  # noqa: S105 - deliberately invalid fixture
    elif fault == "disabled":
        target = replace(target, enabled=False)
    else:
        item = replace(item, kind="RISK")
    wire = WireRequest(
        token, target, item, permit(item, target), TelegramPolicy.REVIEWED_V0_TOKEN_PATH
    )
    with pytest.raises(NotificationError):
        wire.validate(NOW)


@pytest.mark.parametrize("kind", ["event", "configuration", "audit"])
def test_per_table_resource_limits_fail_without_partial_mutation(
    tmp_path: Path, kind: str
) -> None:
    store = NotificationStore(tmp_path / "app.sqlite")
    with closing(sqlite3.connect(tmp_path / "app.sqlite")) as db:
        if kind == "event":
            db.execute(
                "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<10000) INSERT INTO qhn_events(owner,event_id,dedupe,payload,payload_digest,local_status,published_at) SELECT 'FIXTURE','N-'||x,'D-'||x,X'7B7D','fixture','EXPIRED','old' FROM n"
            )
        elif kind == "configuration":
            db.execute(
                "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<10000) INSERT INTO qhn_configs SELECT 'FIXTURE-'||x,1,X'7B7D','fixture' FROM n"
            )
        else:
            db.execute(
                "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<50000) INSERT INTO qhn_audit(owner,identity,operation,status,at,previous_hash,event_hash) SELECT 'FIXTURE','I','X','X','old','x','x' FROM n"
            )
        db.commit()
    with pytest.raises(NotificationError, match="CAPACITY"):
        if kind == "configuration":
            store.configure("OWNER", config(), expected_revision=0, now=NOW)
        else:
            store.publish("OWNER", event(), now=NOW)
    assert store.inbox("OWNER") == ()


@pytest.mark.parametrize(
    "body", ['{"password": "private"}', '"api_key": "private"', "bot_token = private"]
)
def test_raw_secret_configuration_cannot_be_embedded_in_visible_event_text(
    body: str,
) -> None:
    with pytest.raises(NotificationError, match="UNSAFE"):
        replace(event(), body=body).validate()


def test_extreme_calendar_values_fail_before_expiry_arithmetic() -> None:
    with pytest.raises(NotificationError, match="TIMESTAMP_RANGE"):
        replace(event(), created_at=datetime(9999, 12, 30, tzinfo=UTC)).validate()
