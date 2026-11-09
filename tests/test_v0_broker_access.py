"""Private broker profiles/read proofs and real-risk offline protocol integration."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI, HTTPException, Request
from test_v0_paper_workflow import LocalClient, control, launch
from test_v0_paper_workflow import build as paper_build

from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.credentials import VaultError
from quant_hunter.paper_brokers.clients import PaperBroker
from quant_hunter.paper_brokers.common import BrokerError, Response, canonical, digest
from quant_hunter.paper_brokers.common import Request as WireRequest
from quant_hunter.paper_brokers.journal import Submission
from quant_hunter.web import broker_access as module
from quant_hunter.web.broker_access import BrokerAccess
from quant_hunter.web.broker_routes import Profile, install_broker_routes
from quant_hunter.web.state import AccessError, Session, User

KEY = "SyntheticPaperKey_12345"
SECRET = "SyntheticPaperSecret_12345"  # noqa: S105 -- offline format fixture
ALPACA = "11111111-1111-1111-1111-111111111111"
OANDA = "101-001-123456789-001"


class AccountWire:
    def __init__(self) -> None:
        self.requests: list[WireRequest] = []
        self.response: Response | None = None

    def send(self, request: WireRequest) -> Response:
        self.requests.append(request)
        assert request.method == "GET" and request.body is None
        if self.response is not None:
            return self.response
        if request.target == "/v2/account":
            return Response(
                200,
                canonical(
                    {
                        "id": ALPACA,
                        "currency": "USD",
                        "cash": "10000",
                        "equity": "10000",
                        "status": "ACTIVE",
                        "trading_blocked": False,
                        "account_blocked": False,
                    }
                ),
            )
        if request.target == "/v3/accounts":
            return Response(200, canonical({"accounts": [{"id": OANDA}]}))
        return Response(
            200,
            canonical(
                {
                    "account": {
                        "id": OANDA,
                        "currency": "USD",
                        "balance": "10000",
                        "NAV": "10000",
                    }
                }
            ),
        )


def build(
    tmp_path: Path, *, wire: AccountWire | None = None
) -> tuple[BrokerAccess, User]:
    paper, owner = paper_build(tmp_path / "runtime")
    return BrokerAccess(
        paper.state,
        paper,
        paper.lab.objects,
        tmp_path / "private",
        tmp_path / "application",
        read_transport=wire,
        resource=lambda user, kind: nullcontext(),
    ), owner


def configure(
    access: BrokerAccess, owner: User, provider: str = "ALPACA", *, revision: int = 0
) -> JsonRecord:
    return access.configure(
        owner,
        provider,
        account_id=ALPACA if provider == "ALPACA" else OANDA,
        key=KEY,
        secret=SECRET if provider == "ALPACA" else None,
        credential_source="ALPACA_PAPER" if provider == "ALPACA" else "OANDA_PRACTICE",
        paper_only_confirmed=True,
        expected_revision=revision,
    )


def paused(access: BrokerAccess, owner: User, market: str = "EQUITY") -> JsonRecord:
    job = launch(access.paper, owner, market, lookback=1)
    assert access.paper.process_one() and access.paper.process_one()
    return control(access.paper, owner, job, "PAUSE")


def result(operation: JsonRecord) -> JsonRecord:
    return cast(JsonRecord, operation["result"])


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_profile_is_private_masked_cas_revocable_and_read_only(
    tmp_path: Path, provider: str, caplog: pytest.LogCaptureFixture
) -> None:
    wire = AccountWire()
    access, owner = build(tmp_path, wire=wire)
    profile = configure(access, owner, provider)
    assert profile["revision"] == 1 and profile["enabled"] is True
    assert profile["credential_purpose"] == "PAPER_OR_READ_ONLY"
    assert profile["credential_origin_evidence"] == "OWNER_ASSERTED_PAPER_ONLY"
    assert not wire.requests
    assert (
        KEY not in repr(profile) + caplog.text
        and SECRET not in repr(profile) + caplog.text
    )
    assert access._vault().list_masked()[0]["purpose"] == "PAPER_OR_READ_ONLY"
    for file in tmp_path.rglob("*"):
        if file.is_file():
            assert (
                KEY.encode() not in file.read_bytes()
                and SECRET.encode() not in file.read_bytes()
            )
    with pytest.raises(BrokerError, match="STALE"):
        configure(access, owner, provider)
    read = access.test_connection(owner, provider, expected_revision=1)
    assert result(read)["status"] == "VERIFIED_ACCOUNT_READ"
    assert result(read)["evidence_mode"] == "RECORDED_FIXTURE"
    assert result(read)["orders_authorized"] is False
    assert len(wire.requests) == (1 if provider == "ALPACA" else 2)
    assert (
        access.evidence(owner, cast(str, read["operation_id"]))["verified_digests"]
        == result(read)["capture_digests"]
    )
    assert access.revoke(owner, provider, expected_revision=1)["enabled"] is False
    assert access.revoke(owner, provider, expected_revision=2)["revision"] == 2
    assert (
        access.evidence(owner, cast(str, read["operation_id"]))["verified_digests"]
        == result(read)["capture_digests"]
    )
    assert (
        result(access.test_connection(owner, provider, expected_revision=2))["status"]
        == "FAILED"
    )


def test_unconfigured_transport_is_truthfully_blocked_without_secret_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    configure(access, owner)
    monkeypatch.setattr(
        access, "_vault", lambda: pytest.fail("must not consume credentials")
    )
    operation = access.test_connection(owner, "ALPACA", expected_revision=1)
    assert result(operation)["status"] == "BLOCKED_EXTERNAL"
    assert access.operations(owner) == [operation]


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "LIVE"),
        ("credential_source", "ALPACA_LIVE"),
        ("paper_only_confirmed", False),
        ("paper_only_confirmed", 1),
        ("expected_revision", True),
        ("expected_revision", 63),
        ("account_id", "wrong"),
        ("key", "short"),
        ("secret", None),
    ],
)
def test_invalid_profiles_do_not_create_vault(
    tmp_path: Path, field: str, value: object
) -> None:
    access, owner = build(tmp_path)
    arguments: dict[str, object] = {
        "provider": "ALPACA",
        "account_id": ALPACA,
        "key": KEY,
        "secret": SECRET,
        "credential_source": "ALPACA_PAPER",
        "paper_only_confirmed": True,
        "expected_revision": 0,
    }
    arguments[field] = value
    with pytest.raises(BrokerError):
        access.configure(owner, **arguments)  # type: ignore[arg-type]
    assert not access.private_root.exists()


def test_profile_capacity_preserves_disable_headroom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    monkeypatch.setattr(module, "MAX_PROFILES", 2)
    configure(access, owner)
    with pytest.raises(BrokerError, match="CAPACITY"):
        configure(access, owner, revision=1)
    assert access.revoke(owner, "ALPACA", expected_revision=1)["revision"] == 2


def test_concurrent_configuration_preserves_one_active_secret(tmp_path: Path) -> None:
    access, owner = build(tmp_path)

    def attempt(_: int) -> str:
        try:
            configure(access, owner)
            return "OK"
        except BrokerError:
            return "STALE"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["OK", "STALE"]
    assert access.status(owner)[0]["revision"] == 1


@pytest.mark.parametrize("code", [401, 403, 404, 429, 500])
def test_account_failures_are_retained_without_exposing_provider_errors(
    tmp_path: Path, code: int
) -> None:
    wire = AccountWire()
    wire.response = Response(code, b'{"error":"fixture provider content"}')
    access, owner = build(tmp_path, wire=wire)
    configure(access, owner)
    operation = access.test_connection(owner, "ALPACA", expected_revision=1)
    assert result(operation)["status"] == "FAILED"
    assert "fixture provider content" not in repr(operation)
    assert len(cast(list[object], result(operation)["capture_digests"])) == 1
    assert access.get(owner, cast(str, operation["operation_id"])) == operation


@pytest.mark.parametrize(
    "body",
    [
        canonical({"id": "wrong"}),
        b'{"secret":"' + SECRET.encode() + b'"}',
        ('{"error":"' + "".join(f"\\u{ord(c):04x}" for c in SECRET) + '",').encode(),
        b"x" * 2_097_153,
    ],
    ids=[
        "wrong-account",
        "reflected-secret",
        "escaped-malformed-secret",
        "oversized-body",
    ],
)
def test_identity_and_reflected_secret_faults_do_not_claim_success(
    tmp_path: Path, body: bytes
) -> None:
    wire = AccountWire()
    wire.response = Response(200, body)
    access, owner = build(tmp_path, wire=wire)
    configure(access, owner)
    operation = access.test_connection(owner, "ALPACA", expected_revision=1)
    assert result(operation)["status"] == "FAILED"
    assert SECRET not in repr(operation)
    if body != canonical({"id": "wrong"}):
        assert result(operation)["capture_digests"] == []


@pytest.mark.parametrize(
    "provider,market", [("ALPACA", "EQUITY"), ("ALPACA", "ETF"), ("OANDA", "FX_SPOT")]
)
def test_actual_risk_reservation_drives_offline_client_and_durable_journal(
    tmp_path: Path, provider: str, market: str
) -> None:
    access, owner = build(tmp_path)
    job = paused(access, owner, market)
    paper_id, revision = cast(str, job["id"]), cast(int, job["revision"])
    before = access.paper.engine.load(paper_id, str(owner.id))
    operation = access.dry_run(owner, provider, paper_id, expected_revision=revision)
    assert result(operation)["status"] == "ACKNOWLEDGED", operation
    assert result(operation)["external_requests"] == 0
    assert result(operation)["broker_fill_claimed"] is False
    assert result(operation)["economic_book_changed"] is False
    assert access.paper.engine.load(paper_id, str(owner.id)) == before
    assert (
        access.paper.lab.get_run(cast(str, job["experiment_id"]))["variants_attempted"]
        == 0
    )
    assert not access.private_root.exists()
    if market == "ETF":
        proof = module._record(
            access.objects.read_bytes(cast(str, result(operation)["proof_digest"]))
        )
        assert proof["symbol_mapping"] == {
            "canonical": "SYNTH_ETF",
            "offline_protocol": "QHSYNTH",
        }
        contracts = cast(list[JsonRecord], proof["http_fixture_contracts"])
        post = next(row for row in contracts if row["method"] == "POST")
        assert post["provider"] == "ALPACA" and post["target"] == "/v2/orders"
        request = module._record(
            access.objects.read_bytes(cast(str, post["request_digest"]))
        )
        assert request["symbol"] == "QHSYNTH"
        assert request["qty"] == str(before.reservations[0].remaining)
        assert request["side"] == before.reservations[0].side.lower()
        assert request["type"] == "market" and request["time_in_force"] == "day"
        retained_book = cast(JsonRecord, cast(JsonRecord, proof["snapshot"])["book"])
        assert cast(list[JsonRecord], retained_book["instruments"])[0]["kind"] == "ETF"
    assert access.evidence(owner, cast(str, operation["operation_id"]))[
        "verified_digests"
    ] == [result(operation)["proof_digest"]]
    assert (
        access.dry_run(owner, provider, paper_id, expected_revision=revision)
        == operation
    )
    restarted = BrokerAccess(
        access.state,
        access.paper,
        access.objects,
        tmp_path / "private",
        tmp_path / "application",
        resource=lambda user, kind: nullcontext(),
    )
    assert (
        restarted.dry_run(owner, provider, paper_id, expected_revision=revision)
        == operation
    )
    control(access.paper, owner, job, "RESUME")
    job = control(access.paper, owner, job, "PAUSE")
    repeated = restarted.dry_run(
        owner, provider, paper_id, expected_revision=cast(int, job["revision"])
    )
    assert result(repeated)["reason"] == "RESERVATION_ALREADY_DEMONSTRATED_OR_UNKNOWN"


def test_etf_cannot_be_routed_to_oanda_offline_protocol(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = paused(access, owner, "ETF")
    identity = cast(str, job["id"])
    before = access.paper.engine.load(identity, str(owner.id))
    operation = access.dry_run(
        owner, "OANDA", identity, expected_revision=cast(int, job["revision"])
    )
    assert result(operation)["status"] == "FAILED"
    assert result(operation)["reason"] == "PAPER_PROVIDER_INSTRUMENT_MISMATCH"
    assert result(operation)["external_requests"] == 0
    assert result(operation)["proof_digest"] is None
    assert access.paper.engine.load(identity, str(owner.id)) == before


def test_owner_checks_and_resource_admission_precede_secret_and_protocol(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    other = access.state.create_user(
        "reader", "synthetic reader password", "reader", bootstrap=False
    )
    for action in (
        lambda: access.status(other),
        lambda: configure(access, other),
        lambda: access.operations(other),
        lambda: access.get(other, "unknown"),
    ):
        with pytest.raises(AccessError):
            action()
    closed = BrokerAccess(
        access.state,
        access.paper,
        access.objects,
        tmp_path / "private",
        tmp_path / "application",
    )
    with pytest.raises(BrokerError, match="RESOURCE_BOUNDARY"):
        closed.test_connection(owner, "ALPACA", expected_revision=1)
    with pytest.raises(BrokerError, match="RESOURCE_BOUNDARY"):
        closed.dry_run(owner, "ALPACA", "unknown", expected_revision=1)
    assert closed.operations(owner) == []

    @contextmanager
    def revoke_role(user: User, kind: str) -> Iterator[None]:
        with access.state.connection() as db:
            db.execute("UPDATE users SET role='reader' WHERE id=?", (owner.id,))
        yield

    access.resource = revoke_role
    with pytest.raises(AccessError):
        access.test_connection(owner, "ALPACA", expected_revision=1)


def client(access: BrokerAccess | None, owner: User) -> LocalClient:
    app = FastAPI()

    def auth(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        if request.headers.get("x-auth") != "valid" or (
            mutation and request.headers.get("x-csrf") != "valid"
        ):
            raise HTTPException(403, "Denied")
        return Session(user, "csrf")

    user = owner
    install_broker_routes(app, auth, access)
    return LocalClient(app)


def test_closed_routes_mask_secrets_and_require_owner_csrf(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    web = client(access, owner)
    assert web.get("/api/paper-brokers/configuration").status_code == 403
    web.headers = {"x-auth": "valid"}
    schema = web.get("/api/paper-brokers/profile-schema")
    assert schema.status_code == 200 and schema.json()["additionalProperties"] is False
    payload = {
        "account_id": ALPACA,
        "key": KEY,
        "secret": SECRET,
        "credential_source": "ALPACA_PAPER",
        "paper_only_confirmed": True,
        "expected_revision": 0,
    }
    assert SECRET not in repr(Profile.model_validate(payload))
    assert (
        web.post("/api/paper-brokers/ALPACA/configuration", json=payload).status_code
        == 403
    )
    web.headers["x-csrf"] = "valid"
    success = web.post("/api/paper-brokers/ALPACA/configuration", json=payload)
    assert (
        success.status_code == 200
        and SECRET not in success.text
        and KEY not in success.text
    )
    assert (
        web.post(
            "/api/paper-brokers/ALPACA/test", json={"expected_revision": 1}
        ).json()["result"]["status"]
        == "BLOCKED_EXTERNAL"
    )
    for raw in (
        b'{"expected_revision":1,"expected_revision":1}',
        b"x" * 4097,
        canonical({"expected_revision": 1, "secret": SECRET}),
    ):
        response = web.post("/api/paper-brokers/ALPACA/revoke", content=raw)
        assert response.status_code in {400, 413} and SECRET not in response.text
    assert (
        web.post(
            "/api/paper-brokers/ALPACA/revoke", json={"expected_revision": 1}
        ).status_code
        == 200
    )
    assert web.post("/api/paper-brokers/ALPACA/orders", json={}).status_code == 404


class Crash(BaseException):
    """A simulated process exit, bypassing recoverable operation errors."""


def test_interrupted_protocol_keeps_unknown_and_cannot_resubmit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    job = paused(access, owner)
    original = access.journal.reserve

    def interrupted(*args: object, **kwargs: object) -> tuple[bool, Submission]:
        original(*args, **kwargs)  # type: ignore[arg-type]
        raise Crash

    monkeypatch.setattr(access.journal, "reserve", interrupted)
    paper_id, revision = cast(str, job["id"]), cast(int, job["revision"])
    with pytest.raises(Crash):
        access.dry_run(owner, "ALPACA", paper_id, expected_revision=revision)
    retained = access.operations(owner)[0]
    assert result(retained)["status"] == "UNKNOWN"
    restarted = BrokerAccess(
        access.state,
        access.paper,
        access.objects,
        tmp_path / "private",
        tmp_path / "application",
        resource=lambda user, kind: nullcontext(),
    )
    monkeypatch.setattr(
        module._ProtocolFixture,
        "send",
        lambda self, request: pytest.fail("unknown attempt cannot resend"),
    )
    assert (
        restarted.dry_run(owner, "ALPACA", paper_id, expected_revision=revision)
        == retained
    )
    with restarted.journal._connect() as db:
        assert db.execute("SELECT count(*) FROM actions").fetchone()[0] == 1
        assert db.execute("SELECT state FROM receipts").fetchone()[0] == "UNKNOWN"


def test_stale_state_after_protocol_retains_partial_proof_without_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    job = paused(access, owner)
    original = PaperBroker.submit

    def changed(client: PaperBroker, *args: object, **kwargs: object) -> Submission:
        submission = original(client, *args, **kwargs)  # type: ignore[arg-type]
        control(access.paper, owner, job, "RESUME")
        return submission

    monkeypatch.setattr(PaperBroker, "submit", changed)
    operation = access.dry_run(
        owner,
        "ALPACA",
        cast(str, job["id"]),
        expected_revision=cast(int, job["revision"]),
    )
    assert result(operation)["status"] == "FAILED"
    assert result(operation)["proof_digest"] is not None
    assert access.evidence(owner, cast(str, operation["operation_id"]))[
        "verified_digests"
    ] == [result(operation)["proof_digest"]]


def test_parallel_dry_runs_claim_only_one_native_action(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = paused(access, owner)

    def run(_: int) -> JsonRecord:
        return access.dry_run(
            owner,
            "ALPACA",
            cast(str, job["id"]),
            expected_revision=cast(int, job["revision"]),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        operations = list(pool.map(run, range(2)))
    assert operations[0]["operation_id"] == operations[1]["operation_id"]
    assert any(
        result(operation)["status"] == "ACKNOWLEDGED" for operation in operations
    )
    assert all(
        result(operation)["status"] in {"ACKNOWLEDGED", "UNKNOWN"}
        for operation in operations
    )
    with access.journal._connect() as db:
        assert db.execute("SELECT count(*) FROM actions").fetchone()[0] == 1


def test_wrong_provider_foreign_session_and_busy_state_cannot_reach_broker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    job = paused(access, owner)
    monkeypatch.setattr(
        module._ProtocolFixture,
        "send",
        lambda self, request: pytest.fail("refused before fixture"),
    )
    operation = access.dry_run(
        owner,
        "OANDA",
        cast(str, job["id"]),
        expected_revision=cast(int, job["revision"]),
    )
    assert result(operation)["reason"] == "PAPER_PROVIDER_INSTRUMENT_MISMATCH"
    other = access.state.create_user(
        "other", "synthetic other owner password", "owner", bootstrap=False
    )
    operation = access.dry_run(
        other,
        "ALPACA",
        cast(str, job["id"]),
        expected_revision=cast(int, job["revision"]),
    )
    assert (
        result(operation)["status"] == "FAILED"
        and result(operation)["proof_digest"] is None
    )
    with pytest.raises(AccessError):
        access.get(owner, cast(str, operation["operation_id"]))
    active = control(access.paper, owner, job, "RESUME")
    operation = access.dry_run(
        owner,
        "ALPACA",
        cast(str, job["id"]),
        expected_revision=cast(int, active["revision"]),
    )
    assert result(operation)["status"] == "FAILED"
    with access.journal._connect() as db:
        assert db.execute("SELECT count(*) FROM actions").fetchone()[0] == 0


def test_account_profile_revoked_during_response_cannot_claim_verified(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    configure(access, owner)

    class RevokingWire(AccountWire):
        def send(self, request: WireRequest) -> Response:
            with access.state.connection() as db:
                current = access._profile_row(db, owner.id, "ALPACA")
            assert current is not None
            access._append_profile(
                owner, {**current, "revision": 2, "enabled": False}, 1
            )
            return super().send(request)

    access.read_transport = RevokingWire()
    operation = access.test_connection(owner, "ALPACA", expected_revision=1)
    assert result(operation)["status"] == "FAILED"
    assert result(operation)["reason"] == "PAPER_PROFILE_CHANGED"
    assert len(cast(list[object], result(operation)["capture_digests"])) == 1


def test_evidence_rejects_corrupted_or_rebound_capture(tmp_path: Path) -> None:
    access, owner = build(tmp_path, wire=AccountWire())
    configure(access, owner)
    operation = access.test_connection(owner, "ALPACA", expected_revision=1)
    capture_digest = cast(list[str], result(operation)["capture_digests"])[0]
    capture = module._record(access.objects.read_bytes(capture_digest))
    rebound = access.objects.publish(
        canonical({**capture, "operation_id": "foreign"})
    ).digest
    with access.state.connection() as db:
        receipt = db.execute(
            "SELECT payload FROM qhb_receipts WHERE operation_id=?",
            (operation["operation_id"],),
        ).fetchone()
        envelope = module._record(receipt[0])
        cast(JsonRecord, envelope["result"])["capture_digests"] = [rebound]
        raw = canonical(envelope)
        db.execute("DROP TRIGGER qhb_receipts_UPDATE")
        db.execute(
            "UPDATE qhb_receipts SET payload=?,digest=? WHERE operation_id=?",
            (raw, digest(raw), operation["operation_id"]),
        )
    with pytest.raises(BrokerError, match="CAPTURE_BINDING"):
        access.evidence(owner, cast(str, operation["operation_id"]))
    identity = access.objects.publish(b"bounded proof").digest
    path = access.objects.object_path(identity)
    path.write_bytes(b"tampered")
    with pytest.raises(BrokerError, match="DIGEST"):
        access._read_object(identity)


def test_bound_operation_and_evidence_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    monkeypatch.setattr(module, "MAX_OPERATIONS", 1)
    access.test_connection(owner, "ALPACA", expected_revision=1)
    with pytest.raises(BrokerError, match="CAPACITY"):
        access.test_connection(owner, "ALPACA", expected_revision=1)
    identity = access.objects.publish(b"x" * 129).digest
    with pytest.raises(BrokerError, match="BOUND"):
        access._read_object(identity, 128)
    with pytest.raises(BrokerError, match="BOUND"):
        module._evidence({"x": "x" * 2_097_152})
    with pytest.raises(BrokerError, match="UNSUPPORTED"):
        module._evidence({"x": object()})


@pytest.mark.parametrize(
    "error,status",
    [
        (AccessError("secret error"), 403),
        (BrokerError("secret error"), 409),
        (VaultError("secret error"), 503),
        (RuntimeError("secret error"), 503),
    ],
)
def test_routes_refuse_provider_internal_errors_without_reflection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception, status: int
) -> None:
    access, owner = build(tmp_path)

    def fail(user: User) -> list[JsonRecord]:
        raise error

    monkeypatch.setattr(access, "status", fail)
    web = client(access, owner)
    web.headers = {"x-auth": "valid", "x-csrf": "valid"}
    response = web.get("/api/paper-brokers/configuration")
    assert response.status_code == status and "secret error" not in response.text


def test_all_read_routes_and_strict_confirmation_shape(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    web = client(access, owner)
    web.headers = {"x-auth": "valid", "x-csrf": "valid"}
    assert web.get("/api/paper-brokers/configuration").status_code == 200
    operation = web.post(
        "/api/paper-brokers/ALPACA/test", json={"expected_revision": 1}
    ).json()
    identity = operation["operation_id"]
    assert web.get("/api/paper-brokers/operations").json() == [operation]
    assert web.get("/api/paper-brokers/operations/" + identity).json() == operation
    assert (
        web.post(
            "/api/paper-brokers/operations/" + identity + "/verify", json={}
        ).json()["verified_digests"]
        == []
    )
    invalid = web.post(
        "/api/paper-brokers/ALPACA/dry-run",
        json={"paper_id": "PAPER-" + "f" * 32, "expected_revision": 1},
    )
    assert invalid.status_code == 200 and invalid.json()["result"]["status"] == "FAILED"
    assert (
        web.post(
            "/api/paper-brokers/ALPACA/configuration",
            json={
                "account_id": ALPACA,
                "key": KEY,
                "secret": SECRET,
                "credential_source": "ALPACA_PAPER",
                "paper_only_confirmed": 1,
                "expected_revision": 0,
            },
        ).status_code
        == 400
    )
    assert not access.private_root.exists()
    web = client(None, owner)
    web.headers = {"x-auth": "valid"}
    assert web.get("/api/paper-brokers/configuration").status_code == 503


@pytest.mark.parametrize(
    "field,value,rehash",
    [
        ("enabled", "yes", True),
        ("owner_id", 999, True),
        ("vault_slot", "arbitrary", True),
        ("account_id", "bad", True),
        ("revision", 64, True),
        ("enabled", False, False),
    ],
)
def test_profile_integrity_and_schema_refuse_hostile_local_records(
    tmp_path: Path, field: str, value: object, rehash: bool
) -> None:
    access, owner = build(tmp_path)
    configure(access, owner)
    with access.state.connection() as db:
        profile = access._profile_row(db, owner.id, "ALPACA")
        assert profile is not None
        raw = canonical({**profile, field: value})
        db.execute("DROP TRIGGER qhb_profiles_UPDATE")
        if rehash:
            db.execute("UPDATE qhb_profiles SET payload=?,digest=?", (raw, digest(raw)))
        else:
            db.execute("UPDATE qhb_profiles SET payload=?", (raw,))
    with pytest.raises(BrokerError):
        access.status(owner)


@pytest.mark.parametrize(
    "attack", ["operation-hash", "operation-binding", "receipt-hash", "receipt-binding"]
)
def test_operation_receipt_identity_is_verified(tmp_path: Path, attack: str) -> None:
    access, owner = build(tmp_path)
    operation = access.test_connection(owner, "ALPACA", expected_revision=1)
    table = "qhb_operations" if attack.startswith("operation") else "qhb_receipts"
    select, update, update_hash = (
        (
            "SELECT payload FROM qhb_operations",
            "UPDATE qhb_operations SET payload=?",
            "UPDATE qhb_operations SET payload=?,digest=?",
        )
        if table == "qhb_operations"
        else (
            "SELECT payload FROM qhb_receipts",
            "UPDATE qhb_receipts SET payload=?",
            "UPDATE qhb_receipts SET payload=?,digest=?",
        )
    )
    with access.state.connection() as db:
        row = db.execute(select).fetchone()
        value = module._record(row[0])
        value["owner_id" if table == "qhb_operations" else "request_digest"] = "foreign"
        raw = canonical(value)
        db.execute("DROP TRIGGER " + table + "_UPDATE")
        if attack.endswith("hash"):
            db.execute(update, (raw,))
        else:
            db.execute(update_hash, (raw, digest(raw)))
    with pytest.raises(BrokerError, match=r"INTEGRITY|BINDING"):
        access.get(owner, cast(str, operation["operation_id"]))


def test_safe_internal_identity_and_missing_operation_refusals(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    with pytest.raises(BrokerError, match="RECORD_REQUIRED"):
        module._record(b"[]")
    with pytest.raises(BrokerError, match="MISSING"):
        access._finish("missing", {})
    with pytest.raises(BrokerError, match="STALE"):
        access.revoke(owner, "ALPACA", expected_revision=1)
    operation, _ = access._begin(
        owner, "ALPACA", "ACCOUNT_READ", {"profile_revision": 1}
    )
    with pytest.raises(BrokerError, match="CONFLICTING"):
        access._begin(
            owner, "ALPACA", "ACCOUNT_READ", {"profile_revision": 2}, identity=operation
        )


def replace_receipt(
    access: BrokerAccess,
    operation_id: str,
    changes: JsonRecord,
    remove: str | None = None,
) -> None:
    with access.state.connection() as db:
        row = db.execute(
            "SELECT payload FROM qhb_receipts WHERE operation_id=?", (operation_id,)
        ).fetchone()
        value = module._record(row[0])
        saved = cast(JsonRecord, value["result"])
        if remove is not None:
            del saved[remove]
        saved.update(changes)
        raw = canonical(value)
        db.execute("DROP TRIGGER IF EXISTS qhb_receipts_UPDATE")
        db.execute(
            "UPDATE qhb_receipts SET payload=?,digest=? WHERE operation_id=?",
            (raw, digest(raw), operation_id),
        )


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_completed_account_read_requires_exact_capture_count(
    tmp_path: Path, provider: str
) -> None:
    access, owner = build(tmp_path, wire=AccountWire())
    configure(access, owner, provider)
    operation = access.test_connection(owner, provider, expected_revision=1)
    identity = cast(str, operation["operation_id"])
    replace_receipt(access, identity, {}, "capture_digests")
    with pytest.raises(BrokerError, match="REQUIRED_EVIDENCE"):
        access.evidence(owner, identity)


def test_completed_protocol_requires_proof_and_retained_source_archive(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = paused(access, owner)
    operation = access.dry_run(
        owner,
        "ALPACA",
        cast(str, job["id"]),
        expected_revision=cast(int, job["revision"]),
    )
    assert result(operation)["status"] == "ACKNOWLEDGED"
    identity = cast(str, operation["operation_id"])
    saved_digest = result(operation)["proof_digest"]
    replace_receipt(access, identity, {}, "proof_digest")
    with pytest.raises(BrokerError, match="REQUIRED_EVIDENCE"):
        access.evidence(owner, identity)
    replace_receipt(access, identity, {"proof_digest": saved_digest})
    assert access.evidence(owner, identity)["verified_digests"] == [saved_digest]
    environment = module._record(
        access.objects.read_bytes(access.paper.lab.environment_digest)
    )
    source_path = access.objects.object_path(
        cast(str, environment["source_snapshot_digest"])
    )
    source_path.write_bytes(b"corrupted source archive")
    with pytest.raises(BrokerError, match=r"DIGEST|HISTORICAL_RECEIPT_BINDING"):
        access.evidence(owner, identity)


@pytest.mark.parametrize(
    "provider,market", [("ALPACA", "EQUITY"), ("OANDA", "FX_SPOT")]
)
def test_rehashed_protocol_graph_cannot_replace_semantic_identities(
    tmp_path: Path, provider: str, market: str
) -> None:
    access, owner = build(tmp_path)
    job = paused(access, owner, market)
    operation = access.dry_run(
        owner,
        provider,
        cast(str, job["id"]),
        expected_revision=cast(int, job["revision"]),
    )
    identity = cast(str, operation["operation_id"])
    original = module._record(
        access.objects.read_bytes(cast(str, result(operation)["proof_digest"]))
    )
    for attack in (
        "environment",
        "experiment",
        "provider",
        "target",
        "method",
        "status",
        "submission",
        "request",
        "response",
        "sequence",
        "symbol",
        "strategy",
        "forged-report",
    ):
        proof = deepcopy(original)
        contracts = cast(list[JsonRecord], proof["http_fixture_contracts"])
        changes: JsonRecord = {}
        if attack == "environment":
            implementation = module._record(
                access.objects.read_bytes(cast(str, proof["implementation_digest"]))
            )
            implementation["environment_digest"] = access.objects.publish(
                b'{"different":true}'
            ).digest
            proof["implementation_digest"] = access.objects.publish(
                canonical(implementation)
            ).digest
        elif attack == "experiment":
            cast(JsonRecord, proof["context"])["experiment_id"] = "EXP-foreign"
            changes["paper_context"] = proof["context"]
        elif attack in {"provider", "target", "method", "status"}:
            contracts[0][attack] = 201 if attack == "status" else "foreign"
        elif attack == "submission":
            cast(JsonRecord, proof["submission"])["broker_order_id"] = "foreign"
        elif attack == "request":
            contracts[-1]["request_digest"] = access.objects.publish(
                b'{"arbitrary":"order"}'
            ).digest
        elif attack == "response":
            raw = module._record(
                access.objects.read_bytes(cast(str, contracts[-1]["response_digest"]))
            )
            raw["unexpected"] = "fabricated"
            contracts[-1]["response_digest"] = access.objects.publish(
                canonical(raw)
            ).digest
        elif attack == "sequence":
            proof["http_fixture_contracts"] = list(contracts[:-1])
        elif attack == "symbol":
            proof["symbol_mapping"] = {
                "canonical": "different",
                "offline_protocol": "arbitrary",
            }
        elif attack == "strategy":
            cast(JsonRecord, proof["context"])["strategy_id"] = "STR-foreign"
            changes["paper_context"] = proof["context"]
        else:
            context = cast(JsonRecord, proof["context"])
            report = module._record(
                access.objects.read_bytes(cast(str, context["report_digest"]))
            )
            altered = cast(JsonRecord, proof["snapshot"])
            altered["equity"] = "12345"
            report["snapshot"] = altered
            context["snapshot_digest"] = digest(canonicalize_json(altered))
            context["report_digest"] = access.objects.publish(
                module._evidence(report)
            ).digest
            changes["paper_context"] = context
        changes["proof_digest"] = access.objects.publish(module._evidence(proof)).digest
        replace_receipt(access, identity, {**result(operation), **changes})
        with pytest.raises(BrokerError, match=r"BINDING|BOUND"):
            access.evidence(owner, identity)
    replace_receipt(access, identity, result(operation))
    control(access.paper, owner, job, "RESUME")
    assert access.evidence(owner, identity)["verified_digests"] == [
        result(operation)["proof_digest"]
    ]


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_rehashed_account_captures_bind_exact_historical_profile_and_parser(
    tmp_path: Path, provider: str
) -> None:
    access, owner = build(tmp_path, wire=AccountWire())
    configure(access, owner, provider)
    operation = access.test_connection(owner, provider, expected_revision=1)
    identity = cast(str, operation["operation_id"])
    captures = cast(list[str], result(operation)["capture_digests"])
    original = module._record(access.objects.read_bytes(captures[0]))
    for attack in (
        "profile",
        "target",
        "sequence",
        "account-raw",
        "account-result",
        "mode",
    ):
        capture = deepcopy(original)
        changes: JsonRecord = {}
        if attack == "profile":
            capture["profile_digest"] = "sha256:" + "f" * 64
        elif attack == "target":
            capture["target"] = "/v2/orders"
        elif attack == "sequence":
            capture["target"] = "/foreign"
        elif attack == "account-raw":
            value = module._record(
                access.objects.read_bytes(cast(str, capture["raw_digest"]))
            )
            if provider == "ALPACA":
                value["id"] = "22222222-2222-2222-2222-222222222222"
            else:
                cast(list[JsonRecord], value["accounts"])[0]["id"] = (
                    "101-001-999999999-001"
                )
            capture["raw_digest"] = access.objects.publish(canonical(value)).digest
        elif attack == "account-result":
            changes["account"] = {
                **cast(JsonRecord, result(operation)["account"]),
                "cash": "54321",
            }
        else:
            capture["evidence_mode"] = "HISTORICAL_REAL"
        rebound = access.objects.publish(canonical(capture)).digest
        changes["capture_digests"] = [rebound, *captures[1:]]
        replace_receipt(access, identity, {**result(operation), **changes})
        with pytest.raises(BrokerError):
            access.evidence(owner, identity)
    replace_receipt(access, identity, result(operation))
    assert access.evidence(owner, identity)["verified_digests"] == captures
