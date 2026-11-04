"""Documented paper REST adapters. Root issues risk authorization; no signal code."""

from __future__ import annotations

import http.client
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlencode

from .common import (
    BrokerConfig,
    BrokerError,
    OfflineTransport,
    OrderIntent,
    Request,
    Response,
    RiskAuthorization,
    Transport,
    action_bytes,
    canonical,
    checked_response,
    decimal,
    digest,
    identifier,
    parse,
    record,
    records,
    timestamp,
)
from .journal import Submission, SubmissionJournal
from .transport import validate_request


@dataclass(frozen=True)
class Account:
    account_id: str
    currency: str
    cash: Decimal
    equity: Decimal
    trading_enabled: bool
    environment_evidence: str = "FIXED_OFFICIAL_PAPER_HOST_AND_ACCOUNT_ID"


@dataclass(frozen=True)
class BrokerOrder:
    broker_order_id: str
    client_order_id: str
    instrument: str
    side: str
    quantity: Decimal
    order_type: str
    time_in_force: str
    status: str
    created_at: str
    filled_quantity: Decimal | None
    average_fill_price: Decimal | None
    price: Decimal | None
    position_fill: str | None


@dataclass(frozen=True)
class Evidence:
    status: int
    raw: bytes = field(repr=False)
    digest: str
    retrieved_at: datetime
    request: bytes = field(repr=False)
    request_digest: str


class PaperBroker:
    """No default network transport and no mutation without bound RiskAuthorization.

    Injected transports are trusted host/test implementations. External requests
    require explicit FixedPaperHTTPS enablement. A successful fixture is not an
    authenticated broker test or assurance about live execution.
    """

    def __init__(
        self,
        config: BrokerConfig,
        journal: SubmissionJournal,
        *,
        transport: Transport | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.journal = journal
        self.transport = transport or OfflineTransport()
        self.last_evidence: Evidence | None = None

    def capabilities(self) -> dict[str, object]:
        return {
            "provider": self.config.provider,
            "mode": "BROKER_PAPER",
            "order_types": ("MARKET", "LIMIT", "STOP"),
            "submit": True,
            "query_by_client_id": True,
            "cancel": True,
            "replace": True,
            "bounded_rest_polling": True,
            "streaming": False,
            "automatic_retry": False,
            "authenticated_smoke": "BLOCKED_EXTERNAL",
            "risk_authorization_required": True,
        }

    def _send(
        self,
        method: str,
        target: str,
        body: dict[str, object] | None = None,
        *,
        authorization: RiskAuthorization | None = None,
        authorization_payload: bytes | None = None,
    ) -> Response:
        self.last_evidence = None
        request = Request(
            self.config.provider,
            method,
            target,
            self.config.credentials,
            canonical(body) if body is not None else None,
            authorization,
            self.config if authorization else None,
            authorization_payload,
        )
        validate_request(request)
        if isinstance(self.transport, OfflineTransport):
            raise BrokerError("BLOCKED_EXTERNAL_TRANSPORT_NOT_CONFIGURED")
        try:
            received = self.transport.send(request)
        except TimeoutError:
            raise BrokerError("NETWORK_TIMEOUT") from None
        except OSError, http.client.HTTPException, ValueError, TypeError, RuntimeError:
            raise BrokerError("NETWORK_FAILURE") from None
        result = checked_response(received, self.config.credentials)
        safe_request = canonical(
            {
                "provider": self.config.provider,
                "host": request.host,
                "method": method,
                "target": target,
                "body": body,
            }
        )
        self.last_evidence = Evidence(
            result.status,
            result.body,
            digest(result.body),
            datetime.now(UTC),
            safe_request,
            digest(safe_request),
        )
        return result

    def _get(self, target: str) -> object:
        response = self._send("GET", target)
        if response.status != 200:
            raise BrokerError(f"HTTP_{response.status}")
        return parse(response.body)

    @property
    def _base(self) -> str:
        return "/v3/accounts/" + self.config.account_id

    def account(self) -> Account:
        if self.config.provider == "ALPACA":
            value = record(self._get("/v2/account"))
            if value.get("id") != self.config.account_id:
                raise BrokerError("ACCOUNT_IDENTITY_MISMATCH")
            currency = identifier(value.get("currency"), r"[A-Z]{3}")
            enabled = (
                value.get("status") == "ACTIVE"
                and value.get("trading_blocked") is False
                and value.get("account_blocked") is False
            )
            return Account(
                self.config.account_id,
                currency,
                decimal(value.get("cash"), signed=True),
                decimal(value.get("equity"), signed=True),
                enabled,
            )
        accounts = records(record(self._get("/v3/accounts")).get("accounts"))
        identities = [
            identifier(row.get("id"), r"[0-9]{3}-[0-9]{3}-[0-9]{6,12}-[0-9]{3}")
            for row in accounts
        ]
        if identities.count(self.config.account_id) != 1 or len(set(identities)) != len(
            identities
        ):
            raise BrokerError("ACCOUNT_IDENTITY_MISMATCH")
        chosen = next(
            row for row in accounts if row.get("id") == self.config.account_id
        )
        if "mt4AccountID" in chosen:
            raise BrokerError("MT4_CLIENT_EXTENSIONS_UNSUPPORTED")
        value = record(record(self._get(self._base + "/summary")).get("account"))
        if value.get("id") != self.config.account_id:
            raise BrokerError("ACCOUNT_IDENTITY_MISMATCH")
        return Account(
            self.config.account_id,
            identifier(value.get("currency"), r"[A-Z]{3}"),
            decimal(value.get("balance"), signed=True),
            decimal(value.get("NAV"), signed=True),
            True,
        )

    def test_connection(self) -> Account:
        return self.account()

    def positions(self) -> tuple[dict[str, object], ...]:
        self.account()
        output: list[dict[str, object]] = []
        if self.config.provider == "ALPACA":
            for row in records(self._get("/v2/positions")):
                side = row.get("side")
                if side not in ("long", "short"):
                    raise BrokerError("POSITION_SCHEMA")
                output.append(
                    {
                        "instrument": identifier(
                            row.get("symbol"), r"[A-Z][A-Z0-9.-]{0,14}"
                        ),
                        "quantity": decimal(row.get("qty"), signed=True),
                        "side": side,
                        "cost_basis": decimal(row.get("cost_basis"), signed=True),
                    }
                )
        else:
            for row in records(
                record(self._get(self._base + "/openPositions")).get("positions")
            ):
                long = decimal(record(row.get("long")).get("units"), signed=True)
                short = decimal(record(row.get("short")).get("units"), signed=True)
                if long < 0 or short > 0:
                    raise BrokerError("POSITION_SCHEMA")
                output.append(
                    {
                        "instrument": identifier(
                            row.get("instrument"), r"[A-Z]{3}_[A-Z]{3}"
                        ),
                        "long_units": long,
                        "short_units": short,
                    }
                )
        if len({str(row["instrument"]) for row in output}) != len(output):
            raise BrokerError("DUPLICATE_POSITION")
        return tuple(output)

    def _normalize(
        self, value: object, *, expected_client: str | None = None
    ) -> BrokerOrder:
        row = record(value)
        if self.config.provider == "ALPACA":
            client_id = identifier(row.get("client_order_id"))
            order_id = identifier(row.get("id"), r"[a-f0-9-]{36}")
            instrument = identifier(row.get("symbol"), r"[A-Z][A-Z0-9.-]{0,14}")
            side = identifier(row.get("side")).upper()
            qty = decimal(row.get("qty"), positive=True)
            filled = decimal(row.get("filled_qty"))
            status = identifier(row.get("status"), r"[a-z_]{1,32}").upper()
            if (
                filled > qty
                or (status == "FILLED" and filled != qty)
                or (status == "PARTIALLY_FILLED" and not 0 < filled < qty)
            ):
                raise BrokerError("ORDER_FILL_CONTRADICTION")
            average = (
                decimal(row.get("filled_avg_price"), positive=True) if filled else None
            )
            order_type = identifier(row.get("type")).upper()
            tif = identifier(row.get("time_in_force")).upper()
            created = timestamp(row.get("created_at"))
            price = (
                decimal(
                    row.get("limit_price" if order_type == "LIMIT" else "stop_price"),
                    positive=True,
                )
                if order_type in {"LIMIT", "STOP"}
                else None
            )
            position_fill = None
        else:
            client_id = identifier(record(row.get("clientExtensions")).get("id"))
            order_id = identifier(row.get("id"), r"[0-9]{1,20}")
            instrument = identifier(row.get("instrument"), r"[A-Z]{3}_[A-Z]{3}")
            units = decimal(row.get("units"), signed=True)
            if not units:
                raise BrokerError("ORDER_ZERO_UNITS")
            qty, side = abs(units), "BUY" if units > 0 else "SELL"
            status = identifier(row.get("state"), r"[A-Z_]{1,32}")
            filled, average = (
                None,
                None,
            )  # Order state alone is not a fill-quantity ledger.
            order_type = identifier(row.get("type"))
            tif = identifier(row.get("timeInForce"))
            created = timestamp(row.get("createTime"))
            price = (
                decimal(row.get("price"), positive=True)
                if order_type in {"LIMIT", "STOP"}
                else None
            )
            position_fill = identifier(row.get("positionFill"))
        if expected_client is not None and client_id != expected_client:
            raise BrokerError("CLIENT_ORDER_ID_MISMATCH")
        if side not in {"BUY", "SELL"}:
            raise BrokerError("ORDER_SIDE_SCHEMA")
        return BrokerOrder(
            order_id,
            client_id,
            instrument,
            side,
            qty,
            order_type,
            tif,
            status,
            created,
            filled,
            average,
            price,
            position_fill,
        )

    def get_order(self, client_order_id: str) -> BrokerOrder:
        identifier(client_order_id)
        self.account()
        if self.config.provider == "ALPACA":
            value = self._get(
                "/v2/orders:by_client_order_id?"
                + urlencode({"client_order_id": client_order_id})
            )
        else:
            value = record(self._get(self._base + "/orders/@" + client_order_id)).get(
                "order"
            )
        return self._normalize(value, expected_client=client_order_id)

    def orders(self) -> tuple[BrokerOrder, ...]:
        self.account()
        values = (
            self._get("/v2/orders?status=all&limit=100&direction=asc")
            if self.config.provider == "ALPACA"
            else record(self._get(self._base + "/pendingOrders")).get("orders")
        )
        result = tuple(self._normalize(value) for value in records(values))
        if len({order.broker_order_id for order in result}) != len(result) or len(
            {order.client_order_id for order in result}
        ) != len(result):
            raise BrokerError("DUPLICATE_ORDER")
        return result

    def _instrument(self, intent: OrderIntent) -> None:
        if self.config.provider == "ALPACA":
            value = record(self._get("/v2/assets/" + intent.instrument))
            if (
                value.get("symbol") != intent.instrument
                or value.get("class") != "us_equity"
                or value.get("status") != "active"
                or value.get("tradable") is not True
            ):
                raise BrokerError("INSTRUMENT_NOT_TRADABLE")
            if intent.price is not None:
                tick = Decimal(".01") if intent.price >= 1 else Decimal(".0001")
                if intent.price % tick:
                    raise BrokerError("PRICE_TICK_GRID")
        else:
            values = records(
                record(
                    self._get(
                        self._base
                        + "/instruments?"
                        + urlencode({"instruments": intent.instrument})
                    )
                ).get("instruments"),
                maximum=1,
            )
            if (
                len(values) != 1
                or values[0].get("name") != intent.instrument
                or values[0].get("type") != "CURRENCY"
            ):
                raise BrokerError("INSTRUMENT_NOT_TRADABLE")
            value = values[0]
            precision, price_precision = (
                value.get("tradeUnitsPrecision"),
                value.get("displayPrecision"),
            )
            if (
                type(precision) is not int
                or type(price_precision) is not int
                or not 0 <= precision <= 9
                or not 0 <= price_precision <= 9
            ):
                raise BrokerError("INSTRUMENT_PRECISION")
            if (
                intent.quantity % Decimal(10) ** -precision
                or intent.quantity
                < decimal(value.get("minimumTradeSize"), positive=True)
                or intent.quantity
                > decimal(value.get("maximumOrderUnits"), positive=True)
            ):
                raise BrokerError("QUANTITY_GRID_OR_LIMIT")
            if (
                intent.price is not None
                and intent.price % Decimal(10) ** -price_precision
            ):
                raise BrokerError("PRICE_TICK_GRID")

    def _body(self, intent: OrderIntent) -> dict[str, object]:
        if self.config.provider == "ALPACA":
            value: dict[str, object] = {
                "symbol": intent.instrument,
                "qty": str(intent.quantity),
                "side": intent.side.lower(),
                "type": intent.order_type.lower(),
                "time_in_force": intent.time_in_force.lower(),
                "client_order_id": intent.client_order_id,
                "order_class": "simple",
                "extended_hours": False,
            }
            if intent.price is not None:
                value[
                    "limit_price" if intent.order_type == "LIMIT" else "stop_price"
                ] = str(intent.price)
            return value
        order: dict[str, object] = {
            "instrument": intent.instrument,
            "units": str(intent.quantity if intent.side == "BUY" else -intent.quantity),
            "type": intent.order_type,
            "timeInForce": intent.time_in_force,
            "positionFill": intent.position_fill,
            "clientExtensions": {"id": intent.client_order_id},
        }
        if intent.price is not None:
            order["price"] = str(intent.price)
        return {"order": order}

    def submit(
        self, intent: OrderIntent, authorization: RiskAuthorization
    ) -> Submission:
        return self._mutate("SUBMIT", intent, None, authorization)

    def cancel(
        self, original_client_id: str, authorization: RiskAuthorization
    ) -> Submission:
        return self._mutate("CANCEL", None, original_client_id, authorization)

    def replace(
        self,
        original_client_id: str,
        intent: OrderIntent,
        authorization: RiskAuthorization,
    ) -> Submission:
        return self._mutate("REPLACE", intent, original_client_id, authorization)

    def _mutate(
        self,
        action: str,
        intent: OrderIntent | None,
        original_client_id: str | None,
        authorization: RiskAuthorization,
    ) -> Submission:
        request = action_bytes(action, intent, original_client_id)
        authorization.validate(self.config, request, datetime.now(UTC))
        if intent is not None:
            intent.validate(self.config.provider)
        account = self.account()
        if not account.trading_enabled:
            raise BrokerError("ACCOUNT_NOT_TRADING_ENABLED")
        original = (
            self.get_order(original_client_id)
            if original_client_id is not None
            else None
        )
        if intent is not None:
            self._instrument(intent)
        if (
            original is not None
            and intent is not None
            and (
                original.instrument != intent.instrument
                or original.side != intent.side
                or original.order_type != intent.order_type
                or original.client_order_id == intent.client_order_id
                or (
                    original.filled_quantity is not None
                    and intent.quantity < original.filled_quantity
                )
            )
        ):
            raise BrokerError("REPLACEMENT_CONTRADICTION")
        if (
            action == "REPLACE"
            and original is not None
            and original.status not in {"NEW", "PARTIALLY_FILLED", "PENDING"}
        ):
            raise BrokerError("REPLACEMENT_STATE_UNSUPPORTED")
        # Verification may consume time; expiry is checked again immediately before reservation/send.
        authorization.validate(self.config, request, datetime.now(UTC))
        client_id = (
            intent.client_order_id
            if intent is not None
            else identifier(original_client_id)
        )
        fresh, previous = self.journal.reserve(
            self.config, action, client_id, request, authorization
        )
        if not fresh:
            return previous
        if self.config.provider == "ALPACA":
            target = (
                "/v2/orders"
                if original is None
                else "/v2/orders/" + original.broker_order_id
            )
            method = {"SUBMIT": "POST", "CANCEL": "DELETE", "REPLACE": "PATCH"}[action]
            body = self._body(intent) if intent is not None else None
            if action == "REPLACE" and body is not None:
                body = {
                    key: value
                    for key, value in body.items()
                    if key
                    in {
                        "qty",
                        "limit_price",
                        "stop_price",
                        "time_in_force",
                        "client_order_id",
                    }
                }
        else:
            target = (
                self._base
                + "/orders"
                + ("/@" + original_client_id if original_client_id else "")
                + ("/cancel" if action == "CANCEL" else "")
            )
            method = "POST" if action == "SUBMIT" else "PUT"
            body = self._body(intent) if intent is not None else None
        try:
            try:
                authorization.validate(self.config, request, datetime.now(UTC))
            except BrokerError:
                return self.journal.finish(
                    self.config,
                    authorization.authorization_id,
                    "REJECTED",
                    "RISK_AUTHORIZATION_EXPIRED_BEFORE_WIRE",
                )
            response = self._send(
                method,
                target,
                body,
                authorization=authorization,
                authorization_payload=request,
            )
            if response.status in {400, 401, 403, 404, 422, 429}:
                return self.journal.finish(
                    self.config,
                    authorization.authorization_id,
                    "REJECTED",
                    f"HTTP_{response.status}",
                )
            if response.status not in {200, 201, 204}:
                raise BrokerError("AMBIGUOUS_HTTP_RESULT")
            broker_id: str | None = None
            if self.config.provider == "ALPACA":
                if action == "CANCEL":
                    if response.status != 204 or response.body:
                        raise BrokerError("CANCEL_RESPONSE_SCHEMA")
                    broker_id = original.broker_order_id if original else None
                else:
                    normalized = self._normalize(
                        parse(response.body), expected_client=client_id
                    )
                    if (
                        intent is None
                        or normalized.instrument != intent.instrument
                        or normalized.side != intent.side
                        or normalized.quantity != intent.quantity
                        or normalized.order_type != intent.order_type
                        or normalized.time_in_force != intent.time_in_force
                        or normalized.price != intent.price
                    ):
                        raise BrokerError("ORDER_ACKNOWLEDGEMENT_CONTRADICTION")
                    broker_id = normalized.broker_order_id
            else:
                value = record(parse(response.body))
                transaction = record(
                    value.get(
                        "orderCancelTransaction"
                        if action == "CANCEL"
                        else "orderCreateTransaction"
                    )
                )
                if transaction.get("accountID") != self.config.account_id:
                    raise BrokerError("TRANSACTION_ACCOUNT_MISMATCH")
                expected_type = (
                    "ORDER_CANCEL"
                    if action == "CANCEL"
                    else intent.order_type
                    if intent
                    else None
                )
                if expected_type is None or transaction.get("type") != expected_type:
                    raise BrokerError("TRANSACTION_TYPE_MISMATCH")
                timestamp(transaction.get("time"))
                broker_id = identifier(
                    transaction.get("orderID")
                    if action == "CANCEL"
                    else transaction.get("id"),
                    r"[0-9]{1,20}",
                )
                if (
                    action != "CANCEL"
                    and record(transaction.get("clientExtensions")).get("id")
                    != client_id
                ):
                    raise BrokerError("CLIENT_ORDER_ID_MISMATCH")
                if action != "CANCEL" and (
                    intent is None
                    or transaction.get("instrument") != intent.instrument
                    or decimal(transaction.get("units"), signed=True)
                    != (intent.quantity if intent.side == "BUY" else -intent.quantity)
                    or transaction.get("timeInForce") != intent.time_in_force
                    or transaction.get("positionFill") != intent.position_fill
                    or (
                        intent.price is not None
                        and decimal(transaction.get("price"), positive=True)
                        != intent.price
                    )
                ):
                    raise BrokerError("ORDER_ACKNOWLEDGEMENT_CONTRADICTION")
                if action == "CANCEL" and (
                    original is None or broker_id != original.broker_order_id
                ):
                    raise BrokerError("CANCEL_ORDER_ID_MISMATCH")
            return self.journal.finish(
                self.config,
                authorization.authorization_id,
                "ACKNOWLEDGED",
                "BROKER_ACKNOWLEDGED_NOT_FINAL_FILL",
                broker_id,
            )
        except BrokerError, TypeError, KeyError, ArithmeticError:
            # After reserving a wire attempt, every ambiguous failure remains UNKNOWN.
            return self.journal.finish(
                self.config,
                authorization.authorization_id,
                "UNKNOWN",
                "QUERY_REQUIRED_NO_RESUBMISSION",
            )

    def reconcile_submission(self, action_id: str) -> Submission:
        old = self.journal.load(self.config, action_id)
        if old.state in {"REJECTED", "RECONCILED"}:
            return old
        try:
            order = self.get_order(old.client_order_id)
        except BrokerError:
            return self.journal.finish(
                self.config, action_id, "UNKNOWN", "QUERY_UNRESOLVED_NO_RESUBMISSION"
            )
        request = self.journal.request(self.config, action_id)
        if old.action != "CANCEL":
            values = record(request.get("intent"))
            if (
                order.instrument != values.get("instrument")
                or order.side != values.get("side")
                or order.quantity != decimal(values.get("quantity"), positive=True)
                or order.order_type != values.get("order_type")
                or order.time_in_force != values.get("time_in_force")
                or order.price
                != (
                    decimal(values.get("price"), positive=True)
                    if values.get("price") is not None
                    else None
                )
                or (
                    self.config.provider == "OANDA"
                    and order.position_fill != values.get("position_fill")
                )
            ):
                return self.journal.finish(
                    self.config, action_id, "UNKNOWN", "ORDER_INTENT_BINDING_MISMATCH"
                )
        if old.action == "CANCEL" and order.status not in {
            "CANCELED",
            "CANCELLED",
            "FILLED",
            "EXPIRED",
            "REJECTED",
        }:
            return self.journal.finish(
                self.config,
                action_id,
                "UNKNOWN",
                "CANCEL_NOT_CONFIRMED",
                order.broker_order_id,
            )
        return self.journal.finish(
            self.config,
            action_id,
            "RECONCILED",
            "ORDER_FOUND_" + order.status,
            order.broker_order_id,
        )

    def executions(
        self, cursor: str | None = None
    ) -> tuple[tuple[dict[str, object], ...], str | None]:
        """One bounded page; caller persists cursor. No hidden pagination/retry loop."""
        self.account()
        output: list[dict[str, object]] = []
        if self.config.provider == "ALPACA":
            query = {"direction": "asc", "page_size": "100"}
            if cursor is not None:
                identifier(cursor, r"[0-9]{14,20}::[a-f0-9-]{36}")
                query["page_token"] = cursor
            values = records(
                self._get("/v2/account/activities/FILL?" + urlencode(query))
            )
            for row in values:
                if (
                    row.get("activity_type") != "FILL"
                    or row.get("type") not in ("fill", "partial_fill")
                    or row.get("side") not in ("buy", "sell")
                ):
                    raise BrokerError("FILL_ACTIVITY_SCHEMA")
                quantity = decimal(row.get("qty"), positive=True)
                cumulative = decimal(row.get("cum_qty"), positive=True)
                leaves = decimal(row.get("leaves_qty"))
                if (
                    cumulative < quantity
                    or (row.get("type") == "fill" and leaves != 0)
                    or (row.get("type") == "partial_fill" and leaves <= 0)
                ):
                    raise BrokerError("FILL_ACTIVITY_CONTRADICTION")
                output.append(
                    {
                        "id": identifier(row.get("id"), r"[0-9]{14,20}::[a-f0-9-]{36}"),
                        "order_id": identifier(row.get("order_id"), r"[a-f0-9-]{36}"),
                        "at": timestamp(row.get("transaction_time")),
                        "quantity": quantity,
                        "cumulative_quantity": cumulative,
                        "remaining_quantity": leaves,
                        "instrument": identifier(
                            row.get("symbol"), r"[A-Z][A-Z0-9.-]{0,14}"
                        ),
                        "price": decimal(row.get("price"), positive=True),
                        "side": identifier(row.get("side")),
                        "type": "FILL",
                    }
                )
            next_cursor = str(output[-1]["id"]) if len(output) == 100 else None
        else:
            identifier(cursor, r"[0-9]{1,20}")
            value = record(
                self._get(
                    self._base + "/transactions/sinceid?" + urlencode({"id": cursor})
                )
            )
            values = records(value.get("transactions"), maximum=1000)
            previous = int(cursor or "0")
            for row in values:
                event_id = identifier(row.get("id"), r"[0-9]{1,20}")
                if (
                    int(event_id) <= previous
                    or row.get("accountID") != self.config.account_id
                ):
                    raise BrokerError("TRANSACTION_ORDER_OR_ACCOUNT")
                previous = int(event_id)
                item: dict[str, object] = {
                    "id": event_id,
                    "at": timestamp(row.get("time")),
                    "type": identifier(row.get("type")),
                }
                if item["type"] == "ORDER_FILL":
                    item.update(
                        {
                            "order_id": identifier(row.get("orderID"), r"[0-9]{1,20}"),
                            "units": decimal(row.get("units"), signed=True),
                            "price": decimal(row.get("price"), positive=True),
                            "pl": decimal(row.get("pl"), signed=True),
                            "financing": decimal(row.get("financing"), signed=True),
                            "commission": decimal(row.get("commission")),
                        }
                    )
                output.append(item)
            next_cursor = identifier(value.get("lastTransactionID"), r"[0-9]{1,20}")
            if int(next_cursor) < previous:
                raise BrokerError("CURSOR_REORDER")
        ids = [str(row["id"]) for row in output]
        times = [
            str(row["at"])[:19]
            + "."
            + (
                str(row["at"]).split(".", 1)[1][:-1] if "." in str(row["at"]) else ""
            ).ljust(9, "0")
            for row in output
        ]
        if times != sorted(times):
            raise BrokerError("EXECUTION_TIME_REORDER")
        if (
            len(set(ids)) != len(ids)
            or cursor in ids
            or (cursor is not None and next_cursor == cursor and output)
        ):
            raise BrokerError("DUPLICATE_OR_LOOPING_PAGE")
        return tuple(output), next_cursor
