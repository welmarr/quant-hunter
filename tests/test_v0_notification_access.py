"""Authenticated inbox/vault/HTTP integration, using only offline fake Telegram."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import cast

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request

from quant_hunter.config import JsonRecord
from quant_hunter.credentials import VaultError
from quant_hunter.notifications.telegram import TelegramResult, WireRequest
from quant_hunter.notifications.types import NotificationError, TelegramPolicy
from quant_hunter.web.notification_access import NotificationAccess
from quant_hunter.web.notification_routes import install_notification_routes
from quant_hunter.web.state import AccessError, AppState, Session, User

TOKEN = "123456789:" + "A" * 30  # synthetic format fixture; never a real bot token
OTHER = "123456789:" + "B" * 30
NOW = datetime(2026, 10, 5, 14, tzinfo=UTC)


class Transport:
    def __init__(self, state: str = "SENT") -> None:
        self.state = state
        self.calls: list[WireRequest] = []

    def send(self, request: WireRequest) -> TelegramResult:
        request.validate(NOW)
        self.calls.append(request)
        return TelegramResult(
            self.state, "OFFLINE_FIXTURE", 4 if self.state == "SENT" else None
        )


def build(
    tmp_path: Path, *, policy: TelegramPolicy = TelegramPolicy.REVIEWED_V0_TOKEN_PATH
) -> tuple[NotificationAccess, User, Transport]:
    state = AppState(tmp_path / "runtime" / "application.sqlite3")
    owner = state.create_user(
        "owner", "synthetic inbox password", "owner", bootstrap=True
    )
    transport = Transport()
    access = NotificationAccess(
        state,
        tmp_path / "private",
        tmp_path / "application",
        policy=policy,
        transport=transport,
        resource=lambda user: nullcontext(),
        clock=lambda: NOW,
    )
    return access, owner, transport


def configure(
    access: NotificationAccess,
    user: User,
    *,
    revision: int = 0,
    token: str = TOKEN,
    chat: str = "-123456789",
    enabled: bool = True,
) -> JsonRecord:
    return access.configure(
        user,
        bot_token=token,
        allowed_chat_id=chat,
        enabled=enabled,
        expected_revision=revision,
    )


def event_id(result: JsonRecord) -> str:
    return cast(str, cast(JsonRecord, result["event"])["notification_id"])


def test_local_inbox_does_not_create_or_require_vault(tmp_path: Path) -> None:
    access, owner, wire = build(tmp_path, policy=TelegramPolicy.DISABLED)
    event = access.local_test(owner)
    assert event["local_status"] == "DELIVERED_LOCAL"
    assert access.inbox(owner) == [event]
    read = access.mark_read(owner, event_id(event))
    assert read["read_at"]
    assert access.mark_read(owner, event_id(event)) == read
    assert not access.private_root.exists()
    assert wire.calls == []
    assert access.configuration(owner)["revision"] == 0
    assert access.profile_schema(owner)["additionalProperties"] is False
    with pytest.raises(NotificationError, match="POLICY_NOT_APPROVED"):
        access.send(owner, event_id(event), expected_revision=0)


def test_configuration_is_masked_and_private_profile_has_distinct_purpose(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    access, owner, wire = build(tmp_path)
    result = configure(access, owner)
    assert result["credential_purpose"] == "NOTIFICATIONS_ONLY"
    assert result["secret_masked"] == "********"  # noqa: S105 -- literal display mask
    assert result["allowed_chat_masked"] == "****6789"
    assert result["externally_validated"] is False
    assert wire.calls == []
    persisted = b"".join(
        path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    )
    assert TOKEN.encode() not in persisted
    assert TOKEN not in repr(result) + caplog.text
    assert access._vault().list_masked()[0]["purpose"] == "NOTIFICATIONS_ONLY"


@pytest.mark.parametrize(
    "field,value",
    [
        ("bot_token", "not-a-token"),
        ("allowed_chat_id", "@public_channel"),
        ("allowed_chat_id", "4503599627370496"),
        ("enabled", "true"),
        ("expected_revision", True),
        ("expected_revision", -1),
        ("expected_revision", 1000),
    ],
)
def test_invalid_configuration_never_creates_vault(
    tmp_path: Path, field: str, value: object
) -> None:
    access, owner, _ = build(tmp_path)
    values: dict[str, object] = {
        "bot_token": TOKEN,
        "allowed_chat_id": "1234567",
        "enabled": True,
        "expected_revision": 0,
    }
    values[field] = value
    with pytest.raises(NotificationError):
        access.configure(owner, **values)  # type: ignore[arg-type]
    assert not access.private_root.exists()


def test_enabled_policy_and_final_disable_slot_are_required(tmp_path: Path) -> None:
    access, owner, _ = build(tmp_path, policy=TelegramPolicy.DISABLED)
    with pytest.raises(NotificationError, match="POLICY"):
        configure(access, owner)
    assert not access.private_root.exists()
    assert configure(access, owner, enabled=False)["enabled"] is False
    with pytest.raises(NotificationError, match="INVALID_NOTIFICATION_PROFILE"):
        configure(access, owner, revision=999)


def test_readers_only_see_and_mark_own_inbox(tmp_path: Path) -> None:
    access, owner, _ = build(tmp_path)
    event = access.local_test(owner)
    other = access.state.create_user(
        "reader", "synthetic reader password", "reader", bootstrap=False
    )
    assert access.inbox(other) == []
    with pytest.raises(NotificationError, match="NOT_FOUND"):
        access.mark_read(other, event_id(event))
    with pytest.raises(AccessError):
        access.local_test(other)
    for operation in (access.configuration, access.profile_schema):
        with pytest.raises(AccessError):
            operation(other)
    with pytest.raises(AccessError):
        configure(access, other)
    with pytest.raises(AccessError):
        access.send(other, event_id(event), expected_revision=1)
    with access.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (owner.id,))
    with pytest.raises(AccessError):
        access.inbox(owner)
    refreshed = User(owner.id, owner.username, "reader")
    assert access.mark_read(refreshed, event_id(event))["read_at"]


def test_stale_configuration_and_disable_revoke_only_current_version(
    tmp_path: Path,
) -> None:
    access, owner, _ = build(tmp_path)
    configure(access, owner)
    with pytest.raises(NotificationError, match="STALE"):
        configure(access, owner, token=OTHER)
    assert len(access._vault().list_masked()) == 1
    configure(access, owner, revision=1, token=OTHER)
    assert len(access._vault().list_masked()) == 2
    with pytest.raises(NotificationError, match="STALE"):
        access.disable(owner, expected_revision=1)
    assert access.disable(owner, expected_revision=2)["enabled"] is False
    assert sorted(str(item["state"]) for item in access._vault().list_masked()) == [
        "CONFIGURED",
        "REVOKED",
    ]
    with pytest.raises(NotificationError, match="DISABLED_OR_STALE"):
        access.send(owner, event_id(access.local_test(owner)), expected_revision=3)


def test_failed_config_commit_keeps_previous_encrypted_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner, _ = build(tmp_path)
    configure(access, owner)
    original = access.store.configure

    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(access.store, "configure", broken)
    with pytest.raises(OSError):
        configure(access, owner, revision=1, token=OTHER)
    monkeypatch.setattr(access.store, "configure", original)
    current = access.store.configuration(str(owner.id))
    assert current is not None and current.revision == 1
    assert access._vault().with_secret(
        current.vault.provider,
        current.vault.account,
        current.vault.slot,
        lambda raw: json.loads(raw)["bot_token"] == TOKEN,
    )
    assert len(access._vault().list_masked()) == 2


def test_send_is_explicit_bound_and_deduplicated(tmp_path: Path) -> None:
    access, owner, wire = build(tmp_path)
    configure(access, owner)
    event = access.local_test(owner)
    assert wire.calls == []
    with pytest.raises(NotificationError, match="STALE"):
        access.send(owner, event_id(event), expected_revision=0)
    result = access.send(owner, event_id(event), expected_revision=1)
    assert result["state"] == "SENT" and len(wire.calls) == 1
    request = wire.calls[0]
    assert request.config.chat_id == "-123456789"
    assert request.authorization.purpose == "EXPLICIT_TEST"
    configure(access, owner, revision=1, token=OTHER, chat="1234567")
    assert access.send(owner, event_id(event), expected_revision=2) == result
    assert len(wire.calls) == 1
    assert access.inbox(owner)[0]["delivery"] == result


class Crash(BaseException):
    pass


def test_unknown_crash_remains_unknown_without_resubmit_after_restart(
    tmp_path: Path,
) -> None:
    access, owner, wire = build(tmp_path)
    configure(access, owner)
    event = access.local_test(owner)

    class Crashing:
        def send(self, request: WireRequest) -> TelegramResult:
            wire.calls.append(request)
            raise Crash

    access.transport = Crashing()
    with pytest.raises(Crash):
        access.send(owner, event_id(event), expected_revision=1)
    restarted = NotificationAccess(
        access.state,
        tmp_path / "private",
        tmp_path / "application",
        policy=access.policy,
        transport=wire,
        resource=lambda user: nullcontext(),
        clock=lambda: NOW + timedelta(seconds=10),
    )
    result = restarted.send(owner, event_id(event), expected_revision=1)
    assert result["state"] == "UNKNOWN"
    assert len(wire.calls) == 1


def test_resource_callback_is_required_and_runs_before_delivery_reservation(
    tmp_path: Path,
) -> None:
    access, owner, wire = build(tmp_path)
    configure(access, owner)
    event = access.local_test(owner)
    unconfigured = NotificationAccess(
        access.state,
        tmp_path / "private",
        tmp_path / "application",
        policy=access.policy,
        transport=wire,
        clock=lambda: NOW,
    )
    with pytest.raises(NotificationError, match="RESOURCE_BOUNDARY"):
        unconfigured.send(owner, event_id(event), expected_revision=1)
    assert access.store.delivery(str(owner.id), event_id(event)) is None
    checked: list[bool] = []

    @contextmanager
    def resource(user: User) -> Iterator[None]:
        assert user == owner
        with access.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
        checked.append(True)
        yield

    access.resource = resource
    assert access.send(owner, event_id(event), expected_revision=1)["state"] == "SENT"
    assert checked == [True]


def test_resource_account_revocation_prevents_secret_or_send(tmp_path: Path) -> None:
    access, owner, wire = build(tmp_path)
    configure(access, owner)
    event = access.local_test(owner)

    @contextmanager
    def resource(user: User) -> Iterator[None]:
        with access.state.connection() as db:
            db.execute("UPDATE users SET role='reader' WHERE id=?", (user.id,))
        yield

    access.resource = resource
    with pytest.raises(AccessError):
        access.send(owner, event_id(event), expected_revision=1)
    assert wire.calls == []
    assert access.store.delivery(str(owner.id), event_id(event)) is None


def test_concurrent_explicit_clicks_cannot_duplicate_send(tmp_path: Path) -> None:
    access, owner, wire = build(tmp_path)
    configure(access, owner)
    event = access.local_test(owner)
    barrier = Barrier(2)

    def send() -> JsonRecord:
        barrier.wait(5)
        return access.send(owner, event_id(event), expected_revision=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: send(), range(2)))
    assert {item["state"] for item in results} <= {"UNKNOWN", "SENT"}
    assert len(wire.calls) == 1


def test_concurrent_configuration_cas_cannot_replace_winning_secret(
    tmp_path: Path,
) -> None:
    access, owner, _ = build(tmp_path)
    second = NotificationAccess(
        access.state,
        tmp_path / "private",
        tmp_path / "application",
        policy=access.policy,
        clock=lambda: NOW,
    )
    barrier = Barrier(2)

    def save(pair: tuple[NotificationAccess, str]) -> str:
        barrier.wait(5)
        try:
            configure(pair[0], owner, token=pair[1])
        except NotificationError:
            return "CONFLICT"
        return "FIRST" if pair[1] == TOKEN else "SECOND"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [(access, TOKEN), (second, OTHER)]))
    assert results.count("CONFLICT") == 1
    config = access.store.configuration(str(owner.id))
    assert config is not None and config.revision == 1
    winner = TOKEN if "FIRST" in results else OTHER
    assert access._vault().with_secret(
        config.vault.provider,
        config.vault.account,
        config.vault.slot,
        lambda raw: json.loads(raw)["bot_token"] == winner,
    )


@pytest.mark.parametrize(
    "status", ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
)
def test_fixed_job_template_is_owned_deduplicated_and_ignores_raw_errors(
    tmp_path: Path, status: str
) -> None:
    access, owner, wire = build(tmp_path)
    with access.state.connection() as db:
        db.execute(
            "INSERT INTO jobs VALUES('job_fixture',?,?,?,NULL,?)",
            (owner.id, status, "{}", TOKEN),
        )
    event = access.record_job(owner, "job_fixture")
    assert TOKEN not in repr(event)
    assert status in cast(str, cast(JsonRecord, event["event"])["body"])
    access.clock = lambda: NOW + timedelta(seconds=1)
    assert access.record_job(owner, "job_fixture") == event
    assert wire.calls == []
    other = access.state.create_user(
        "other", "synthetic other password", "researcher", bootstrap=False
    )
    with pytest.raises(AccessError):
        access.record_job(other, "job_fixture")


def test_bad_job_state_and_inbox_bounds_fail_closed(tmp_path: Path) -> None:
    access, owner, _ = build(tmp_path)
    with access.state.connection() as db:
        db.execute(
            "INSERT INTO jobs VALUES('job_fixture',?,'SECRET', '{}',NULL,NULL)",
            (owner.id,),
        )
    with pytest.raises(NotificationError, match="UNSUPPORTED_JOB_STATUS"):
        access.record_job(owner, "job_fixture")
    with pytest.raises(NotificationError, match="PAGE_BOUND"):
        access.inbox(owner, limit=101)


def paper_fixture(owner: User) -> JsonRecord:
    return {
        "id": "PAPER-fixture",
        "owner_id": owner.id,
        "status": "ACTIVE",
        "evidence_mode": "SYNTHETIC",
        "experiment_id": None,
        "report": {
            "job_id": "PAPER-fixture",
            "evidence_mode": "SYNTHETIC",
            "signals": [{"index": 3, "explanation": "LAGGED_BID_INCREASE"}],
            "snapshot": {"killed": True, "kill_reason": TOKEN},
            "engine_rejections": [{"reason": TOKEN}],
            "error": TOKEN,
        },
    }


@pytest.mark.parametrize(
    "template,kind", [("STATUS", "SYSTEM"), ("SIGNAL", "SIGNAL"), ("RISK", "RISK")]
)
def test_paper_templates_use_owned_verified_getter_and_only_safe_fields(
    tmp_path: Path, template: str, kind: str
) -> None:
    access, owner, wire = build(tmp_path)
    detail = paper_fixture(owner)
    observed: list[tuple[User, str]] = []

    def read(user: User, identity: str) -> JsonRecord:
        observed.append((user, identity))
        return detail

    access.paper_detail = read
    result = access.record_paper(owner, "PAPER-fixture", template=template)
    assert result is not None and TOKEN not in repr(result)
    event = cast(JsonRecord, result["event"])
    assert event["kind"] == kind and event["mode"] == "SYNTHETIC"
    assert access.record_paper(owner, "PAPER-fixture", template=template) == result
    assert observed == [(owner, "PAPER-fixture")] * 2
    assert wire.calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        "owner",
        "id",
        "evidence",
        "status",
        "report",
        "signals",
        "index",
        "explanation",
        "snapshot",
        "rejections",
    ],
)
def test_paper_notification_refuses_ambiguous_contracts(
    tmp_path: Path, mutation: str
) -> None:
    access, owner, _ = build(tmp_path)
    detail = paper_fixture(owner)
    report = cast(JsonRecord, detail["report"])
    template = "SIGNAL"
    if mutation == "owner":
        detail["owner_id"] = 999
    elif mutation == "id":
        detail["id"] = "other"
    elif mutation == "evidence":
        detail["evidence_mode"] = "HISTORICAL_REAL"
    elif mutation == "status":
        detail["status"] = TOKEN
    elif mutation == "report":
        report["job_id"] = "other"
    elif mutation == "signals":
        report["signals"] = None
    elif mutation in ("index", "explanation"):
        signal: JsonRecord = {"index": 3, "explanation": "WARMUP", mutation: TOKEN}
        report["signals"] = [signal]
    elif mutation == "snapshot":
        template = "RISK"
        report["snapshot"] = {"killed": "False"}
    else:
        template = "RISK"
        report["engine_rejections"] = "none"
    access.paper_detail = lambda user, identity: detail
    with pytest.raises(NotificationError, match="BINDING"):
        access.record_paper(owner, "PAPER-fixture", template=template)
    assert access.inbox(owner) == []


def test_paper_absent_signal_or_risk_does_not_invent_event(tmp_path: Path) -> None:
    access, owner, _ = build(tmp_path)
    with pytest.raises(NotificationError, match="NOT_CONFIGURED"):
        access.record_paper(owner, "PAPER-fixture")
    detail = paper_fixture(owner)
    report = cast(JsonRecord, detail["report"])
    report.update(signals=[], snapshot={"killed": False}, engine_rejections=[])
    access.paper_detail = lambda user, identity: detail
    assert access.record_paper(owner, "PAPER-fixture", template="SIGNAL") is None
    assert access.record_paper(owner, "PAPER-fixture", template="RISK") is None
    assert access.inbox(owner) == []


def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    raw: bytes | None = None,
    value: object = None,
    authenticated: bool = True,
    csrf: bool = True,
) -> httpx.Response:
    async def perform() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://offline.test"
        ) as client:
            return await client.request(
                method,
                path,
                headers={"x-test-auth": str(authenticated), "x-test-csrf": str(csrf)},
                content=raw,
                json=value,
            )

    return asyncio.run(perform())


def test_routes_auth_csrf_closed_private_input_and_masked_validation(
    tmp_path: Path,
) -> None:
    access, owner, wire = build(tmp_path)
    current = [owner]

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        if request.headers.get("x-test-auth") != "True":
            raise HTTPException(401, "Sign in")
        if mutation and request.headers.get("x-test-csrf") != "True":
            raise HTTPException(403, "CSRF")
        if owner and current[0].role != "owner":
            raise HTTPException(403, "Owner required")
        return Session(current[0], "fixture")

    app = FastAPI()
    install_notification_routes(app, authenticated, access)
    base = "/api/notifications"
    assert request(app, "GET", base + "/inbox", authenticated=False).status_code == 401
    assert request(app, "POST", base + "/local-test", csrf=False).status_code == 403
    assert request(app, "GET", base + "/profile-schema").status_code == 200
    assert request(app, "GET", base + "/configuration").json()["configured"] is False
    local = request(app, "POST", base + "/local-test")
    identity = local.json()["event"]["notification_id"]
    assert request(app, "POST", base + f"/inbox/{identity}/read").status_code == 200
    data = {
        "bot_token": TOKEN,
        "allowed_chat_id": "1234567",
        "enabled": True,
        "expected_revision": 0,
    }
    assert request(app, "POST", base + "/configuration", value=data).status_code == 200
    assert (
        request(
            app,
            "POST",
            base + f"/inbox/{identity}/send",
            value={"expected_revision": 1},
        ).json()["state"]
        == "SENT"
    )
    assert len(wire.calls) == 1
    assert (
        request(
            app, "POST", base + "/configuration/disable", value={"expected_revision": 1}
        ).json()["enabled"]
        is False
    )
    for body in (
        b'{"enabled":true,"enabled":false}',
        b'{"bot_token":',
        json.dumps({**data, "unexpected": TOKEN}).encode(),
    ):
        response = request(app, "POST", base + "/configuration", raw=body)
        assert response.status_code == 400
        assert TOKEN not in response.text
    assert (
        request(app, "POST", base + "/configuration", raw=b"x" * 4097).status_code
        == 413
    )
    assert request(app, "GET", base + "/inbox?limit=101").status_code == 400
    current[0] = access.state.create_user(
        "reader", "synthetic reader password", "reader", bootstrap=False
    )
    assert request(app, "GET", base + "/inbox").json() == []
    assert request(app, "POST", base + "/local-test").status_code == 403
    assert request(app, "GET", base + "/configuration").status_code == 403
    unavailable = FastAPI()
    install_notification_routes(unavailable, authenticated, None)
    assert request(unavailable, "GET", base + "/inbox").status_code == 503


def test_route_failures_are_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner, _ = build(tmp_path)

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        return Session(user, "fixture")

    user = owner
    app = FastAPI()
    install_notification_routes(app, authenticated, access)
    for failure, code in [
        (VaultError(TOKEN), 503),
        (RuntimeError(TOKEN), 503),
        (NotificationError(TOKEN), 409),
    ]:

        def fail(*args: object, failure: Exception = failure, **kwargs: object) -> None:
            raise failure

        monkeypatch.setattr(access, "inbox", fail)
        result = request(app, "GET", "/api/notifications/inbox")
        assert result.status_code == code
        assert TOKEN not in result.text


def test_private_root_overlap_and_arbitrary_policy_are_refused(tmp_path: Path) -> None:
    state = AppState(tmp_path / "runtime" / "application.sqlite3")
    with pytest.raises(VaultError, match="OVERLAPS"):
        NotificationAccess(state, tmp_path / "runtime" / "secret", tmp_path / "app")
    with pytest.raises(NotificationError, match="CLOSED_NOTIFICATION_POLICY"):
        NotificationAccess(
            state,
            tmp_path / "secret",
            tmp_path / "app",
            policy="approved",  # type: ignore[arg-type]
        )
