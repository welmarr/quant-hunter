"""Offline paper HTTP contracts only: no real credential, account or broker call."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from typing import cast

import pytest

from quant_hunter.paper_brokers.clients import PaperBroker
from quant_hunter.paper_brokers.common import (
    BrokerConfig,
    BrokerError,
    OrderIntent,
    PaperCredentials,
    Request,
    Response,
    RiskAuthorization,
    action_bytes,
    checked_response,
    digest,
)
from quant_hunter.paper_brokers.journal import SubmissionJournal
from quant_hunter.paper_brokers.transport import (
    FixedPaperHTTPS,
    public_ip,
    validate_request,
)

D = Decimal
ALPACA = "11111111-1111-1111-1111-111111111111"
OANDA = "101-001-1234567-001"
ORDER_ID = "22222222-2222-2222-2222-222222222222"
STAMP = "2024-01-02T14:30:00.123456789Z"
KEY = "SyntheticKey12345678"
SECRET = "SyntheticSecret12345678"  # noqa: S105 - deliberately fake contract credential
ACTIVITY = "20190524113406977::22222222-2222-2222-2222-222222222222"


def response(value: object, status: int = 200) -> Response:
    return Response(status, json.dumps(value).encode())


def config(provider: str = "ALPACA") -> BrokerConfig:
    return BrokerConfig(
        provider,
        "OWNER",
        ALPACA if provider == "ALPACA" else OANDA,
        PaperCredentials(KEY, SECRET if provider == "ALPACA" else None),
    )


def intent(provider: str = "ALPACA", *, client_id: str = "CLIENT-1") -> OrderIntent:
    return OrderIntent(
        client_id,
        "TEST" if provider == "ALPACA" else "EUR_USD",
        D(10),
        "BUY",
        "MARKET",
        "DAY" if provider == "ALPACA" else "FOK",
    )


def authorization(
    conf: BrokerConfig,
    order: OrderIntent | None,
    *,
    action: str = "SUBMIT",
    original: str | None = None,
    action_id: str = "AUTH-1",
) -> RiskAuthorization:
    now = datetime.now(UTC)
    return RiskAuthorization(
        action_id,
        conf.owner_id,
        conf.account_id,
        conf.provider,
        "EXP-EXISTING",
        "STR-EXISTING",
        digest(action_bytes(action, order, original)),
        4,
        now,
        now + timedelta(seconds=30),
    )


class FakeHTTP:
    def __init__(self, provider: str = "ALPACA") -> None:
        self.provider = provider
        self.calls: list[Request] = []
        self.fault: Response | Exception | None = None
        self.account_override: dict[str, object] = {}
        self.order_override: dict[str, object] = {}
        self.asset_override: dict[str, object] = {}
        self.mt4 = False
        self.read_fault: Response | None = None
        self.execution_rows: list[dict[str, object]] = []
        self.position_rows: list[dict[str, object]] = []

    @property
    def mutations(self) -> list[Request]:
        return [request for request in self.calls if request.method != "GET"]

    def alpaca_order(self, **updates: object) -> dict[str, object]:
        result: dict[str, object] = {
            "id": ORDER_ID,
            "client_order_id": "CLIENT-1",
            "symbol": "TEST",
            "side": "buy",
            "qty": "10",
            "filled_qty": "0",
            "filled_avg_price": None,
            "status": "new",
            "type": "market",
            "time_in_force": "day",
            "created_at": STAMP,
        }
        result.update(self.order_override)
        result.update(updates)
        return result

    def oanda_order(self, **updates: object) -> dict[str, object]:
        result: dict[str, object] = {
            "id": "101",
            "clientExtensions": {"id": "CLIENT-1"},
            "instrument": "EUR_USD",
            "units": "10",
            "state": "PENDING",
            "type": "MARKET",
            "timeInForce": "FOK",
            "createTime": STAMP,
            "positionFill": "REDUCE_FIRST",
        }
        result.update(self.order_override)
        result.update(updates)
        return result

    def send(self, request: Request) -> Response:
        validate_request(request)
        self.calls.append(request)
        if request.method != "GET" and self.fault is not None:
            if isinstance(self.fault, Exception):
                raise self.fault
            return self.fault
        if request.method == "GET" and self.read_fault is not None:
            return self.read_fault
        target = request.target
        if self.provider == "ALPACA":
            if target == "/v2/account":
                return response(
                    {
                        "id": ALPACA,
                        "currency": "USD",
                        "cash": "10000",
                        "equity": "10000",
                        "status": "ACTIVE",
                        "trading_blocked": False,
                        "account_blocked": False,
                        **self.account_override,
                    }
                )
            if target.startswith("/v2/assets/"):
                return response(
                    {
                        "symbol": "TEST",
                        "class": "us_equity",
                        "status": "active",
                        "tradable": True,
                        **self.asset_override,
                    }
                )
            if target == "/v2/positions":
                return response(self.position_rows)
            if target.startswith("/v2/orders:by_client_order_id?"):
                return response(self.alpaca_order())
            if target.startswith("/v2/orders?"):
                return response([self.alpaca_order()])
            if target.startswith("/v2/account/activities/FILL?"):
                return response(self.execution_rows)
            if request.method == "DELETE":
                return Response(204, b"")
            if request.method in {"POST", "PATCH"}:
                body = json.loads(request.body or b"{}")
                return response(self.alpaca_order(**body))
        else:
            if target == "/v3/accounts":
                return response(
                    {
                        "accounts": [
                            {"id": OANDA, **({"mt4AccountID": 12} if self.mt4 else {})}
                        ]
                    }
                )
            if target.endswith("/summary"):
                return response(
                    {
                        "account": {
                            "id": OANDA,
                            "currency": "USD",
                            "balance": "10000",
                            "NAV": "10000",
                            **self.account_override,
                        }
                    }
                )
            if "/instruments?" in target:
                return response(
                    {
                        "instruments": [
                            {
                                "name": "EUR_USD",
                                "type": "CURRENCY",
                                "tradeUnitsPrecision": 0,
                                "displayPrecision": 5,
                                "minimumTradeSize": "1",
                                "maximumOrderUnits": "100000",
                                **self.asset_override,
                            }
                        ]
                    }
                )
            if target.endswith("/openPositions"):
                return response({"positions": self.position_rows})
            if target.endswith("/pendingOrders"):
                return response({"orders": [self.oanda_order()]})
            if "/transactions/sinceid?" in target:
                return response(
                    {"transactions": self.execution_rows, "lastTransactionID": "102"}
                )
            if request.method == "GET" and "/orders/@" in target:
                return response({"order": self.oanda_order()})
            if target.endswith("/cancel"):
                return response(
                    {
                        "orderCancelTransaction": {
                            "id": "102",
                            "orderID": "101",
                            "accountID": OANDA,
                            "time": STAMP,
                            "type": "ORDER_CANCEL",
                        }
                    }
                )
            if request.method in {"POST", "PUT"}:
                body = json.loads(request.body or b"{}")
                return response(
                    {
                        "orderCreateTransaction": {
                            "id": "101",
                            "accountID": OANDA,
                            "time": STAMP,
                            **body["order"],
                        }
                    },
                    201,
                )
        raise AssertionError("unexpected offline HTTP route")


def client(tmp_path: Path, provider: str = "ALPACA") -> tuple[PaperBroker, FakeHTTP]:
    fake = FakeHTTP(provider)
    return PaperBroker(
        config(provider), SubmissionJournal(tmp_path / "broker.sqlite"), transport=fake
    ), fake


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_documented_positive_submission_is_paper_only_and_explicitly_authorized(
    tmp_path: Path, provider: str
) -> None:
    broker, fake = client(tmp_path, provider)
    order = intent(provider)
    permit = authorization(broker.config, order)
    result = broker.submit(order, permit)
    assert result.state == "ACKNOWLEDGED" and len(fake.mutations) == 1
    assert result.reason == "BROKER_ACKNOWLEDGED_NOT_FINAL_FILL"
    assert all(
        request.host
        == (
            "paper-api.alpaca.markets"
            if provider == "ALPACA"
            else "api-fxpractice.oanda.com"
        )
        for request in fake.calls
    )
    assert all(
        KEY not in request.target and SECRET not in request.target
        for request in fake.calls
    )
    assert KEY not in repr(broker.config) and SECRET not in repr(fake.mutations)
    assert broker.journal.load(broker.config, permit.authorization_id) == result
    assert broker.capabilities()["authenticated_smoke"] == "BLOCKED_EXTERNAL"
    evidence = broker.last_evidence
    assert evidence is not None
    assert evidence.digest == digest(evidence.raw)
    assert evidence.request_digest == digest(evidence.request)
    assert (
        KEY.encode() not in evidence.request and SECRET.encode() not in evidence.request
    )
    retained_request = json.loads(evidence.request)
    assert retained_request["method"] == "POST"
    assert retained_request["body"] == json.loads(fake.mutations[-1].body or b"null")


@pytest.mark.parametrize("action", ["SUBMIT", "CANCEL"])
@pytest.mark.parametrize("transaction_type", [None, "LIMIT", "ORDER_FILL"])
def test_oanda_missing_or_contradictory_transaction_type_remains_unknown(
    tmp_path: Path, action: str, transaction_type: str | None
) -> None:
    broker, fake = client(tmp_path, "OANDA")
    order = intent("OANDA")
    transaction = {
        "id": "102",
        "orderID": "101",
        "accountID": OANDA,
        "time": STAMP,
        "instrument": "EUR_USD",
        "units": "10",
        "timeInForce": "FOK",
        "positionFill": order.position_fill,
        "clientExtensions": {"id": "CLIENT-1"},
    }
    if transaction_type is not None:
        transaction["type"] = transaction_type
    fake.fault = response(
        {
            "orderCancelTransaction"
            if action == "CANCEL"
            else "orderCreateTransaction": transaction
        }
    )
    permit = authorization(
        broker.config,
        None if action == "CANCEL" else order,
        action=action,
        original="CLIENT-1" if action == "CANCEL" else None,
    )
    result = (
        broker.cancel("CLIENT-1", permit)
        if action == "CANCEL"
        else broker.submit(order, permit)
    )
    assert result.state == "UNKNOWN"
    duplicate = (
        broker.cancel("CLIENT-1", permit)
        if action == "CANCEL"
        else broker.submit(order, permit)
    )
    assert duplicate == result and len(fake.mutations) == 1


def test_malformed_unicode_escaped_credential_is_never_retained(tmp_path: Path) -> None:
    broker, fake = client(tmp_path)
    escaped = "".join(
        chr(92) + "u" + format(ord(character), "04x") for character in SECRET
    )
    fake.read_fault = Response(200, ('{"error":"' + escaped + '",').encode())
    with pytest.raises(BrokerError, match="INVALID_JSON"):
        broker.account()
    assert broker.last_evidence is None


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_exact_duplicate_persists_across_restart_without_another_mutation(
    tmp_path: Path, provider: str
) -> None:
    broker, fake = client(tmp_path, provider)
    order = intent(provider)
    permit = authorization(broker.config, order)
    first = broker.submit(order, permit)
    restarted = PaperBroker(
        broker.config, SubmissionJournal(tmp_path / "broker.sqlite"), transport=fake
    )
    assert restarted.submit(order, permit) == first
    assert len(fake.mutations) == 1
    changed = replace(order, quantity=D(11))
    changed_permit = replace(
        permit, request_digest=digest(action_bytes("SUBMIT", changed, None))
    )
    with pytest.raises(BrokerError, match="CONFLICTING_ACTION_ID"):
        restarted.submit(changed, changed_permit)
    assert len(fake.mutations) == 1


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_timeout_is_unknown_and_lookup_never_resubmits(
    tmp_path: Path, provider: str
) -> None:
    broker, fake = client(tmp_path, provider)
    fake.fault = TimeoutError("private transport detail")
    order = intent(provider)
    permit = authorization(broker.config, order)
    result = broker.submit(order, permit)
    assert result.state == "UNKNOWN"
    assert broker.submit(order, permit).state == "UNKNOWN" and len(fake.mutations) == 1
    assert broker.reconcile_submission(permit.authorization_id).state == "RECONCILED"
    assert len(fake.mutations) == 1


def test_unknown_lookup_404_retains_uncertainty_without_resubmitting(
    tmp_path: Path,
) -> None:
    broker, fake = client(tmp_path)
    fake.fault = TimeoutError()
    order = intent()
    permit = authorization(broker.config, order)
    broker.submit(order, permit)
    fake.read_fault = response({"error": "not found"}, 404)
    assert broker.reconcile_submission(permit.authorization_id).state == "UNKNOWN"
    assert len(fake.mutations) == 1


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429])
def test_definitive_http_refusals_are_retained_and_not_retried(
    tmp_path: Path, provider: str, status: int
) -> None:
    broker, fake = client(tmp_path, provider)
    fake.fault = response({"error": "fixture refusal"}, status)
    order = intent(provider)
    result = broker.submit(order, authorization(broker.config, order))
    assert result.state == "REJECTED" and result.reason == f"HTTP_{status}"
    assert len(fake.mutations) == 1


@pytest.mark.parametrize(
    "failure",
    [
        Response(500, b"{}"),
        Response(503, b"{}"),
        Response(302, b"{}"),
        Response(200, b"not JSON"),
        Response(200, b"{}"),
        Response(200, b'{"id":1,"id":2}'),
        Response(200, b""),
        RuntimeError(SECRET),
        Response(200, b"x" * 2097153),
    ],
    ids=[
        "500",
        "503",
        "redirect",
        "invalid-json",
        "missing",
        "duplicate",
        "empty",
        "exception",
        "oversize",
    ],
)
def test_ambiguous_wire_results_remain_unknown_and_errors_never_leak(
    tmp_path: Path, failure: Response | Exception
) -> None:
    broker, fake = client(tmp_path)
    fake.fault = failure
    order = intent()
    result = broker.submit(order, authorization(broker.config, order))
    assert result.state == "UNKNOWN" and SECRET not in repr(result)
    assert len(fake.mutations) == 1


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_account_identity_mismatch_blocks_before_any_mutation(
    tmp_path: Path, provider: str
) -> None:
    broker, fake = client(tmp_path, provider)
    fake.account_override["id"] = "another-account"
    order = intent(provider)
    with pytest.raises(BrokerError, match="ACCOUNT_IDENTITY"):
        broker.submit(order, authorization(broker.config, order))
    assert not fake.mutations


def test_oanda_mt4_is_refused_before_client_extension_use(tmp_path: Path) -> None:
    broker, fake = client(tmp_path, "OANDA")
    fake.mt4 = True
    order = intent("OANDA")
    with pytest.raises(BrokerError, match="MT4"):
        broker.submit(order, authorization(broker.config, order))
    assert not fake.mutations


@pytest.mark.parametrize(
    "field",
    [
        "account",
        "owner",
        "provider",
        "digest",
        "expired",
        "future",
        "too-long",
        "revision",
        "mode",
    ],
)
def test_risk_authorization_is_required_exact_and_fresh_before_network(
    tmp_path: Path, field: str
) -> None:
    broker, fake = client(tmp_path)
    order = intent()
    permit = authorization(broker.config, order)
    if field == "account":
        permit = replace(permit, account_id="other")
    elif field == "owner":
        permit = replace(permit, owner_id="OTHER")
    elif field == "provider":
        permit = replace(permit, provider="OANDA")
    elif field == "digest":
        permit = replace(permit, request_digest="wrong")
    elif field == "expired":
        permit = replace(
            permit,
            approved_at=permit.approved_at - timedelta(minutes=1),
            expires_at=permit.expires_at - timedelta(minutes=1),
        )
    elif field == "future":
        permit = replace(
            permit,
            approved_at=permit.approved_at + timedelta(minutes=1),
            expires_at=permit.expires_at + timedelta(minutes=1),
        )
    elif field == "too-long":
        permit = replace(permit, expires_at=permit.expires_at + timedelta(seconds=1))
    elif field == "revision":
        permit = replace(permit, risk_revision=-1)
    else:
        permit = replace(permit, mode="LIVE")
    with pytest.raises(BrokerError):
        broker.submit(order, permit)
    assert not fake.calls


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
@pytest.mark.parametrize("kind", ["LIMIT", "STOP"])
def test_documented_price_orders_and_replacement_shapes(
    tmp_path: Path, provider: str, kind: str
) -> None:
    broker, fake = client(tmp_path, provider)
    order = replace(
        intent(provider),
        order_type=kind,
        price=D("1.23450") if provider == "OANDA" else D("101.23"),
        time_in_force="GTC" if provider == "OANDA" else "DAY",
    )
    assert (
        broker.submit(order, authorization(broker.config, order)).state
        == "ACKNOWLEDGED"
    )
    fake.order_override.update(
        {"type": kind if provider == "OANDA" else kind.lower(), "timeInForce": "GTC"}
        if provider == "OANDA"
        else {"type": kind.lower()}
    )
    fake.order_override[
        "price"
        if provider == "OANDA"
        else "limit_price"
        if kind == "LIMIT"
        else "stop_price"
    ] = str(order.price)
    replacement = replace(order, client_order_id="CLIENT-2", quantity=D(12))
    permit = authorization(
        broker.config,
        replacement,
        action="REPLACE",
        original="CLIENT-1",
        action_id="AUTH-2",
    )
    assert broker.replace("CLIENT-1", replacement, permit).state == "ACKNOWLEDGED"
    assert fake.mutations[-1].method == ("PATCH" if provider == "ALPACA" else "PUT")


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_cancel_acknowledgement_is_not_confirmation_of_final_state(
    tmp_path: Path, provider: str
) -> None:
    broker, fake = client(tmp_path, provider)
    permit = authorization(broker.config, None, action="CANCEL", original="CLIENT-1")
    result = broker.cancel("CLIENT-1", permit)
    assert result.state == "ACKNOWLEDGED"
    assert broker.reconcile_submission(permit.authorization_id).state == "UNKNOWN"
    fake.order_override["status" if provider == "ALPACA" else "state"] = (
        "filled" if provider == "ALPACA" else "FILLED"
    )
    if provider == "ALPACA":
        fake.order_override.update(filled_qty="10", filled_avg_price="100")
    assert broker.reconcile_submission(permit.authorization_id).state == "RECONCILED"
    assert len(fake.mutations) == 1


@pytest.mark.parametrize(
    "encoding", ["plain", "json-escaped", "url-escaped", "combined"]
)
def test_reflected_credentials_are_refused_before_evidence_retention(
    tmp_path: Path, encoding: str
) -> None:
    broker, fake = client(tmp_path)
    if encoding == "plain":
        body = json.dumps({"error": SECRET}).encode()
    elif encoding == "json-escaped":
        body = (
            '{"error":"' + "".join(f"\\u{ord(c):04x}" for c in SECRET) + '"}'
        ).encode()
    elif encoding == "url-escaped":
        body = json.dumps({"error": "".join(f"%{ord(c):02x}" for c in SECRET)}).encode()
    else:
        body = (
            '{"error":"' + "".join(f"\\u0025{ord(c):02x}" for c in SECRET) + '"}'
        ).encode()
    fake.fault = Response(500, body)
    order = intent()
    assert broker.submit(order, authorization(broker.config, order)).state == "UNKNOWN"
    assert broker.last_evidence is None
    with pytest.raises(BrokerError, match="REFLECTION"):
        checked_response(Response(200, body), broker.config.credentials)


def test_unconfigured_client_and_default_https_are_explicitly_blocked(
    tmp_path: Path,
) -> None:
    broker = PaperBroker(config(), SubmissionJournal(tmp_path / "broker.sqlite"))
    with pytest.raises(BrokerError, match="BLOCKED_EXTERNAL"):
        broker.account()
    with pytest.raises(BrokerError, match="NETWORK_DISABLED"):
        FixedPaperHTTPS().send(
            Request("ALPACA", "GET", "/v2/account", config().credentials)
        )


@pytest.mark.parametrize(
    "target",
    [
        "https://api.alpaca.markets/v2/orders",
        "//127.0.0.1/test",
        "/v2/orders?api_key=secret",
        "/v2/orders:by_client_order_id?client_order_id=X&client_order_id=Y",
        "/v2/account#fragment",
        "/v2/orders/../../account",
    ],
)
def test_no_arbitrary_or_live_endpoint_can_reach_transport(target: str) -> None:
    with pytest.raises(BrokerError):
        validate_request(Request("ALPACA", "GET", target, config().credentials))


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "0.0.0.0",  # noqa: S104 - rejected fixture; no bind
        "224.0.0.1",
    ],
)
def test_dns_private_addresses_are_refused(
    address: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", (address, 443))]
    )
    with pytest.raises(BrokerError, match="NONPUBLIC"):
        public_ip("paper-api.alpaca.markets")


def test_exact_order_timestamp_nanoseconds_are_preserved(tmp_path: Path) -> None:
    broker, fake = client(tmp_path)
    result = broker.get_order("CLIENT-1")
    assert result.created_at == STAMP
    fake.order_override["created_at"] = "2024-01-02T14:30:00"
    with pytest.raises(BrokerError, match="TIMESTAMP"):
        broker.get_order("CLIENT-1")


def test_alpaca_execution_page_is_bounded_and_duplicate_cursor_is_rejected(
    tmp_path: Path,
) -> None:
    broker, fake = client(tmp_path)
    fake.execution_rows = [
        {
            "id": ACTIVITY,
            "activity_type": "FILL",
            "type": "fill",
            "symbol": "TEST",
            "cum_qty": "2",
            "leaves_qty": "0",
            "order_id": ORDER_ID,
            "transaction_time": STAMP,
            "qty": "2",
            "price": "101.23",
            "side": "buy",
        }
    ]
    page, cursor = broker.executions()
    assert (
        page[0]["quantity"] == D(2)
        and page[0]["price"] == D("101.23")
        and cursor is None
    )
    with pytest.raises(BrokerError, match="DUPLICATE_OR_LOOPING"):
        broker.executions(ACTIVITY)
    fake.execution_rows *= 2
    with pytest.raises(BrokerError, match="DUPLICATE_OR_LOOPING"):
        broker.executions()


def test_oanda_transaction_identity_order_and_actual_cost_fields_are_distinct(
    tmp_path: Path,
) -> None:
    broker, fake = client(tmp_path, "OANDA")
    fake.execution_rows = [
        {
            "id": "102",
            "accountID": OANDA,
            "time": STAMP,
            "type": "ORDER_FILL",
            "orderID": "101",
            "units": "-10",
            "price": "1.20",
            "pl": "2",
            "financing": "-.01",
            "commission": ".02",
        }
    ]
    page, cursor = broker.executions("101")
    assert cursor == "102" and page[0]["units"] == D(-10)
    assert (
        page[0]["pl"] == D(2)
        and page[0]["financing"] == D("-.01")
        and page[0]["commission"] == D(".02")
    )
    fake.execution_rows[0]["accountID"] = "different"
    with pytest.raises(BrokerError, match="TRANSACTION_ORDER_OR_ACCOUNT"):
        broker.executions("101")


def test_public_mutation_signature_requires_explicit_risk_authorization(
    tmp_path: Path,
) -> None:
    broker, fake = client(tmp_path)
    with pytest.raises(TypeError):
        cast(object, broker.submit)(intent())  # type: ignore[operator]
    assert not fake.calls


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_concurrent_same_action_has_at_most_one_wire_submission(
    tmp_path: Path, provider: str
) -> None:
    broker, fake = client(tmp_path, provider)
    order = intent(provider)
    permit = authorization(broker.config, order)
    barrier = Barrier(2)

    def submit() -> str:
        other = PaperBroker(
            broker.config, SubmissionJournal(tmp_path / "broker.sqlite"), transport=fake
        )
        barrier.wait(timeout=5)
        return other.submit(order, permit).state

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(submit)
        b = pool.submit(submit)
        states = (a.result(), b.result())
    assert "ACKNOWLEDGED" in states and set(states) <= {"ACKNOWLEDGED", "UNKNOWN"}
    assert len(fake.mutations) == 1


def test_restart_after_durable_reservation_before_wire_never_sends_again(
    tmp_path: Path,
) -> None:
    broker, fake = client(tmp_path)
    order = intent()
    permit = authorization(broker.config, order)
    fresh, result = broker.journal.reserve(
        broker.config,
        "SUBMIT",
        order.client_order_id,
        action_bytes("SUBMIT", order, None),
        permit,
    )
    assert fresh and result.state == "UNKNOWN"
    restarted = PaperBroker(
        broker.config, SubmissionJournal(tmp_path / "broker.sqlite"), transport=fake
    )
    assert restarted.submit(order, permit).state == "UNKNOWN"
    assert not fake.mutations


def test_same_client_id_cannot_be_reused_with_a_new_approval_id(tmp_path: Path) -> None:
    broker, fake = client(tmp_path)
    order = intent()
    broker.submit(order, authorization(broker.config, order))
    with pytest.raises(BrokerError, match="CLIENT_ORDER_ID_ALREADY_RESERVED"):
        broker.submit(order, authorization(broker.config, order, action_id="OTHER"))
    assert len(fake.mutations) == 1


def test_wrong_owner_cannot_read_or_mutate_prior_submission_journal(
    tmp_path: Path,
) -> None:
    broker, fake = client(tmp_path)
    order = intent()
    broker.submit(order, authorization(broker.config, order))
    other = replace(broker.config, owner_id="OTHER")
    with pytest.raises(BrokerError, match="OWNER_MISMATCH"):
        broker.journal.load(other, "AUTH-1")
    with pytest.raises(BrokerError, match="OWNER_MISMATCH"):
        broker.journal.finish(other, "AUTH-1", "REJECTED", "NO")
    assert len(fake.mutations) == 1


@pytest.mark.parametrize("mutation", ["receipt", "head", "action"])
def test_journal_corruption_is_detected_before_reconciliation(
    tmp_path: Path, mutation: str
) -> None:
    broker, _ = client(tmp_path)
    order = intent()
    broker.submit(order, authorization(broker.config, order))
    with closing(sqlite3.connect(tmp_path / "broker.sqlite")) as db, db:
        if mutation == "receipt":
            db.execute("DROP TRIGGER receipts_update")
            db.execute("UPDATE receipts SET reason='changed'")
        elif mutation == "head":
            db.execute("UPDATE heads SET revision=999")
        else:
            db.execute("DROP TRIGGER actions_update")
            db.execute("UPDATE actions SET request='{}'")
    with pytest.raises(BrokerError, match="JOURNAL_INTEGRITY"):
        broker.journal.load(broker.config, "AUTH-1")


def test_journal_refuses_sql_deletion_and_foreign_database(tmp_path: Path) -> None:
    broker, _ = client(tmp_path)
    order = intent()
    broker.submit(order, authorization(broker.config, order))
    with closing(sqlite3.connect(tmp_path / "broker.sqlite")) as db, db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM receipts")
    foreign = tmp_path / "foreign.sqlite"
    with closing(sqlite3.connect(foreign)) as db, db:
        db.execute("CREATE TABLE unrelated(id TEXT)")
    with pytest.raises(BrokerError, match="JOURNAL_FORMAT"):
        SubmissionJournal(foreign)


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_reconciliation_matches_exact_frozen_intent_not_only_client_id(
    tmp_path: Path, provider: str
) -> None:
    broker, fake = client(tmp_path, provider)
    fake.fault = TimeoutError()
    order = intent(provider)
    permit = authorization(broker.config, order)
    broker.submit(order, permit)
    fake.order_override["qty" if provider == "ALPACA" else "units"] = "999"
    result = broker.reconcile_submission(permit.authorization_id)
    assert (
        result.state == "UNKNOWN" and result.reason == "ORDER_INTENT_BINDING_MISMATCH"
    )
    assert len(fake.mutations) == 1


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_account_positions_and_order_status_queries_are_concrete(
    tmp_path: Path, provider: str
) -> None:
    broker, fake = client(tmp_path, provider)
    fake.position_rows = (
        [{"symbol": "TEST", "qty": "3", "side": "long", "cost_basis": "300"}]
        if provider == "ALPACA"
        else [
            {"instrument": "EUR_USD", "long": {"units": "3"}, "short": {"units": "0"}}
        ]
    )
    assert broker.test_connection().cash == D(10000)
    assert len(broker.positions()) == 1
    orders = broker.orders()
    assert len(orders) == 1 and orders[0].quantity == D(10)
    fake.position_rows *= 2
    with pytest.raises(BrokerError, match="DUPLICATE_POSITION"):
        broker.positions()


@pytest.mark.parametrize(
    "kind",
    [
        "account-blocked",
        "asset",
        "price-grid",
        "quantity-grid",
        "min-size",
        "max-size",
        "instrument-precision",
    ],
)
def test_broker_metadata_rejections_precede_any_wire_mutation(
    tmp_path: Path, kind: str
) -> None:
    provider = (
        "OANDA"
        if kind in {"quantity-grid", "min-size", "max-size", "instrument-precision"}
        else "ALPACA"
    )
    broker, fake = client(tmp_path, provider)
    order = intent(provider)
    if kind == "account-blocked":
        fake.account_override["trading_blocked"] = True
    elif kind == "asset":
        fake.asset_override["tradable"] = False
    elif kind == "price-grid":
        order = replace(order, order_type="LIMIT", price=D("101.001"))
    elif kind == "quantity-grid":
        order = replace(order, quantity=D("1.1"))
    elif kind == "min-size":
        fake.asset_override["minimumTradeSize"] = "100"
    elif kind == "max-size":
        fake.asset_override["maximumOrderUnits"] = "1"
    else:
        fake.asset_override["displayPrecision"] = 999
    with pytest.raises(BrokerError):
        broker.submit(order, authorization(broker.config, order))
    assert not fake.mutations


@pytest.mark.parametrize(
    "kind",
    [
        "side",
        "type",
        "fractional",
        "tif",
        "price-missing",
        "price-extra",
        "negative",
        "infinite",
        "precision",
    ],
)
def test_unsupported_order_combinations_fail_before_network(
    tmp_path: Path, kind: str
) -> None:
    broker, fake = client(tmp_path)
    order = intent()
    if kind == "side":
        order = replace(order, side="UNKNOWN")
    elif kind == "type":
        order = replace(order, order_type="TRAILING_STOP")
    elif kind == "fractional":
        order = replace(order, quantity=D(".5"))
    elif kind == "tif":
        order = replace(order, time_in_force="GTC")
    elif kind == "price-missing":
        order = replace(order, order_type="LIMIT")
    elif kind == "price-extra":
        order = replace(order, price=D(100))
    elif kind == "negative":
        order = replace(order, quantity=D(-1))
    elif kind == "infinite":
        order = replace(order, quantity=D("Infinity"))
    else:
        order = replace(order, quantity=D("1e-30"))
    with pytest.raises(BrokerError):
        broker.submit(order, authorization(broker.config, order))
    assert not fake.calls


def test_lower_level_mutation_transport_also_requires_authorization(
    tmp_path: Path,
) -> None:
    broker, _ = client(tmp_path)
    with pytest.raises(BrokerError, match="RISK_AUTHORIZATION_REQUIRED"):
        validate_request(
            Request("ALPACA", "POST", "/v2/orders", broker.config.credentials, b"{}")
        )


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_wire_body_cannot_change_quantity_after_risk_approval(
    tmp_path: Path, provider: str
) -> None:
    broker, fake = client(tmp_path, provider)
    order = intent(provider)
    permit = authorization(broker.config, order)
    broker.submit(order, permit)
    request = fake.mutations[0]
    body = json.loads(request.body or b"{}")
    if provider == "ALPACA":
        body["qty"] = "999"
    else:
        body["order"]["units"] = "999"
    with pytest.raises(BrokerError, match="RISK_PAYLOAD_BINDING"):
        validate_request(replace(request, body=json.dumps(body).encode()))


@pytest.mark.parametrize("kind", ["mode", "purpose", "secret-shape", "wrong-provider"])
def test_live_or_ambiguous_credential_configuration_is_refused(kind: str) -> None:
    value = config()
    if kind == "mode":
        value = replace(value, mode="LIVE")
    elif kind == "purpose":
        value = replace(value, credentials=replace(value.credentials, purpose="LIVE"))
    elif kind == "secret-shape":
        value = replace(
            value, credentials=PaperCredentials("line\r\ninjection", SECRET)
        )
    else:
        value = replace(value, provider="CUSTOM")
    with pytest.raises(BrokerError):
        value.validate()


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b"[]",
        b"null",
        b'{"x":NaN}',
        b'{"x":1e999999999999999999999999}',
        b"\xff",
        b'{"id":"same","id":"same"}',
    ],
)
def test_malformed_account_responses_fail_as_safe_codes(
    tmp_path: Path, body: bytes
) -> None:
    broker, fake = client(tmp_path)
    fake.read_fault = Response(200, body)
    with pytest.raises(BrokerError) as failure:
        broker.account()
    assert SECRET not in str(failure.value)


@pytest.mark.parametrize(
    "change",
    [
        {"filled_qty": "11"},
        {"status": "filled", "filled_qty": "5", "filled_avg_price": "100"},
        {"status": "partially_filled", "filled_qty": "0"},
        {"side": "unknown"},
        {"client_order_id": "OTHER"},
        {"qty": "bad-number"},
    ],
)
def test_order_read_detects_identity_and_fill_contradictions(
    tmp_path: Path, change: dict[str, object]
) -> None:
    broker, fake = client(tmp_path)
    fake.order_override.update(change)
    with pytest.raises(BrokerError):
        broker.get_order("CLIENT-1")


def test_replacement_of_pending_cancel_cannot_emit_a_second_order(
    tmp_path: Path,
) -> None:
    broker, fake = client(tmp_path)
    fake.order_override["status"] = "pending_cancel"
    order = replace(intent(), client_order_id="CLIENT-2")
    permit = authorization(broker.config, order, action="REPLACE", original="CLIENT-1")
    with pytest.raises(BrokerError, match="REPLACEMENT_STATE"):
        broker.replace("CLIENT-1", order, permit)
    assert not fake.mutations


def test_replacement_cannot_change_original_instrument(tmp_path: Path) -> None:
    broker, fake = client(tmp_path)
    order = replace(intent(), client_order_id="CLIENT-2", instrument="OTHER")
    fake.asset_override["symbol"] = "OTHER"
    permit = authorization(broker.config, order, action="REPLACE", original="CLIENT-1")
    with pytest.raises(BrokerError, match="REPLACEMENT_CONTRADICTION"):
        broker.replace("CLIENT-1", order, permit)
    assert not fake.mutations


def test_oanda_zero_order_and_wrong_sign_position_are_not_normalized(
    tmp_path: Path,
) -> None:
    broker, fake = client(tmp_path, "OANDA")
    fake.order_override["units"] = "0"
    with pytest.raises(BrokerError, match="ZERO_UNITS"):
        broker.get_order("CLIENT-1")
    fake.position_rows = [
        {"instrument": "EUR_USD", "long": {"units": "-1"}, "short": {"units": "0"}}
    ]
    with pytest.raises(BrokerError, match="POSITION_SCHEMA"):
        broker.positions()


@pytest.mark.parametrize("kind", ["instrument", "units", "client", "account"])
def test_oanda_acknowledgement_must_match_the_exact_authorized_request(
    tmp_path: Path, kind: str
) -> None:
    broker, fake = client(tmp_path, "OANDA")
    transaction: dict[str, object] = {
        "id": "101",
        "accountID": OANDA,
        "time": STAMP,
        "type": "MARKET",
        "clientExtensions": {"id": "CLIENT-1"},
        "instrument": "EUR_USD",
        "units": "10",
        "timeInForce": "FOK",
        "positionFill": "REDUCE_FIRST",
    }
    if kind == "instrument":
        transaction["instrument"] = "GBP_USD"
    elif kind == "units":
        transaction["units"] = "999"
    elif kind == "client":
        transaction["clientExtensions"] = {"id": "WRONG"}
    else:
        transaction["accountID"] = "WRONG"
    fake.fault = response({"orderCreateTransaction": transaction}, 201)
    order = intent("OANDA")
    assert broker.submit(order, authorization(broker.config, order)).state == "UNKNOWN"


def test_alpaca_real_cursor_format_and_full_page_yield_bounded_next_cursor(
    tmp_path: Path,
) -> None:
    broker, fake = client(tmp_path)
    fake.execution_rows = [
        {
            "id": f"{20190524113406000 + i}::{ORDER_ID}",
            "activity_type": "FILL",
            "type": "fill",
            "symbol": "TEST",
            "cum_qty": "1",
            "leaves_qty": "0",
            "order_id": ORDER_ID,
            "transaction_time": STAMP,
            "qty": "1",
            "price": "100",
            "side": "buy",
        }
        for i in range(100)
    ]
    result, cursor = broker.executions()
    assert len(result) == 100 and cursor == fake.execution_rows[-1]["id"]
    assert len([r for r in fake.calls if "/activities/" in r.target]) == 1
    fake.execution_rows[0]["transaction_time"] = "2025-01-02T14:30:00Z"
    with pytest.raises(BrokerError, match="TIME_REORDER"):
        broker.executions()


def test_journal_unknown_reads_and_terminal_changes_fail_closed(tmp_path: Path) -> None:
    broker, fake = client(tmp_path)
    order = intent()
    fake.fault = response({}, 403)
    broker.submit(order, authorization(broker.config, order))
    with pytest.raises(BrokerError, match="ACTION_NOT_FOUND"):
        broker.journal.load(broker.config, "MISSING")
    with pytest.raises(BrokerError, match="TERMINAL"):
        broker.journal.finish(broker.config, "AUTH-1", "ACKNOWLEDGED", "WRONG")
    with pytest.raises(BrokerError, match="INVALID_SUBMISSION_STATE"):
        broker.journal.finish(broker.config, "AUTH-1", "LIVE", "WRONG")
    assert broker.reconcile_submission("AUTH-1").state == "REJECTED"


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_price_reconciliation_binds_the_frozen_limit(
    tmp_path: Path, provider: str
) -> None:
    broker, fake = client(tmp_path, provider)
    order = replace(
        intent(provider),
        order_type="LIMIT",
        price=D("1.23"),
        time_in_force="DAY" if provider == "ALPACA" else "GTC",
    )
    permit = authorization(broker.config, order)
    assert broker.submit(order, permit).state == "ACKNOWLEDGED"
    fake.order_override.update(
        {"type": "limit", "limit_price": "1.24"}
        if provider == "ALPACA"
        else {"type": "LIMIT", "timeInForce": "GTC", "price": "1.24"}
    )
    result = broker.reconcile_submission(permit.authorization_id)
    assert (
        result.state == "UNKNOWN" and result.reason == "ORDER_INTENT_BINDING_MISMATCH"
    )
    assert len(fake.mutations) == 1


def test_oanda_cancel_transaction_cannot_acknowledge_a_different_order(
    tmp_path: Path,
) -> None:
    broker, fake = client(tmp_path, "OANDA")
    fake.fault = response(
        {
            "orderCancelTransaction": {
                "id": "102",
                "orderID": "999",
                "accountID": OANDA,
                "time": STAMP,
            }
        }
    )
    permit = authorization(broker.config, None, action="CANCEL", original="CLIENT-1")
    assert broker.cancel("CLIENT-1", permit).state == "UNKNOWN"


@pytest.mark.parametrize("bad", [{}, [], None, 1])
def test_oanda_account_identifier_wrong_types_fail_with_safe_codes(
    tmp_path: Path, bad: object
) -> None:
    broker, fake = client(tmp_path, "OANDA")
    fake.read_fault = response({"accounts": [{"id": bad}]})
    with pytest.raises(BrokerError, match="IDENTIFIER"):
        broker.account()


def test_failed_request_does_not_retain_prior_success_as_current_evidence(
    tmp_path: Path,
) -> None:
    broker, fake = client(tmp_path)
    broker.account()
    assert broker.last_evidence is not None
    fake.fault = TimeoutError("deliberately sensitive exception")
    order = intent()
    assert broker.submit(order, authorization(broker.config, order)).state == "UNKNOWN"
    assert broker.last_evidence is None


@pytest.mark.parametrize(
    "fault", ["large", "client", "action", "authority", "malformed"]
)
def test_direct_journal_reservation_validates_bounded_action_and_authority(
    tmp_path: Path, fault: str
) -> None:
    broker, _ = client(tmp_path)
    order = intent()
    permit = authorization(broker.config, order)
    raw = action_bytes("SUBMIT", order, None)
    client_id, action = order.client_order_id, "SUBMIT"
    if fault == "large":
        raw = b"x" * 16385
    elif fault == "client":
        client_id = "OTHER"
    elif fault == "action":
        action = "REPLACE"
    elif fault == "authority":
        permit = replace(permit, owner_id="OTHER")
    else:
        raw = b"{}"
    with pytest.raises(BrokerError):
        broker.journal.reserve(broker.config, action, client_id, raw, permit)
    with closing(sqlite3.connect(tmp_path / "broker.sqlite")) as database:
        assert database.execute("SELECT count(*) FROM actions").fetchone()[0] == 0
        assert (
            database.execute("SELECT count(*) FROM account_bindings").fetchone()[0] == 0
        )
