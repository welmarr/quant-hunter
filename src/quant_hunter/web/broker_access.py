"""Owner-only paper profiles, bounded account reads and offline protocol proofs."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_OID, uuid4, uuid5

from quant_hunter.config import JsonRecord, canonicalize_json, parse_json_document
from quant_hunter.credentials import CredentialVault, VaultError, protection
from quant_hunter.paper_brokers.clients import PaperBroker
from quant_hunter.paper_brokers.common import (
    HOSTS,
    BrokerConfig,
    BrokerError,
    OrderIntent,
    PaperCredentials,
    Request,
    Response,
    RiskAuthorization,
    Transport,
    action_bytes,
    canonical,
    checked_response,
    digest,
    identifier,
    timestamp,
)
from quant_hunter.paper_brokers.journal import SubmissionJournal
from quant_hunter.paper_brokers.transport import FixedPaperHTTPS, validate_request
from quant_hunter.storage import ImmutableObjectStore
from quant_hunter.web.paper_access import PaperAccess
from quant_hunter.web.state import AccessError, AppState, User

PROVIDERS = ("ALPACA", "OANDA")
MAX_PROFILES = 1000
MAX_OPERATIONS = 1000


def _evidence(value: object) -> bytes:
    def default(item: object) -> str:
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, datetime) and item.tzinfo is UTC:
            return item.isoformat().replace("+00:00", "Z")
        raise BrokerError("UNSUPPORTED_EVIDENCE")

    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=default
    ).encode("ascii")
    if len(raw) > 2_097_152:
        raise BrokerError("BROKER_EVIDENCE_BOUND")
    return raw


def _record(raw: bytes) -> JsonRecord:
    result = parse_json_document(raw)
    if not isinstance(result, dict):
        raise BrokerError("BROKER_RECORD_REQUIRED")
    return result


def _provider(value: str) -> str:
    if value not in PROVIDERS:
        raise BrokerError("PAPER_PROVIDER_REQUIRED")
    return value


def _resource_missing(user: User, operation: str) -> AbstractContextManager[object]:
    raise BrokerError("BROKER_RESOURCE_BOUNDARY_NOT_CONFIGURED")


def _failure(error: Exception) -> str:
    code = str(error)
    return (
        code
        if isinstance(error, BrokerError) and re.fullmatch(r"[A-Z0-9_]{1,64}", code)
        else "BROKER_OPERATION_FAILED"
    )


def _fixture_config(provider: str, owner_id: int) -> BrokerConfig:
    return BrokerConfig(
        provider,
        str(owner_id),
        str(uuid5(NAMESPACE_OID, "qh-offline-owner-" + str(owner_id)))
        if provider == "ALPACA"
        else f"101-001-{owner_id:09d}-001",
        PaperCredentials(
            "SyntheticProtocolKeyOnly",
            "SyntheticProtocolSecretOnly" if provider == "ALPACA" else None,
        ),
    )


class _ReadTransport:
    def __init__(
        self, access: BrokerAccess, user: User, profile: JsonRecord, operation_id: str
    ) -> None:
        self.access, self.user, self.profile = access, user, profile
        self.operation_id = operation_id
        self.captures: list[str] = []
        self.total_bytes = 0

    def send(self, request: Request) -> Response:
        if (
            request.method != "GET"
            or request.body is not None
            or request.authorization is not None
        ):
            raise BrokerError("READ_ONLY_BROKER_BOUNDARY")
        if len(self.captures) >= 2:
            raise BrokerError("ACCOUNT_QUERY_BOUND")
        self.access._actor(self.user)
        if self.access._profile(self.user, request.provider) != self.profile:
            raise BrokerError("PAPER_PROFILE_CHANGED")
        validate_request(request)
        transport = self.access.read_transport
        if transport is None:
            raise BrokerError("BLOCKED_EXTERNAL_TRANSPORT_NOT_CONFIGURED")
        response = checked_response(transport.send(request), request.credentials)
        self.total_bytes += len(response.body)
        if self.total_bytes > 2_097_152:
            raise BrokerError("ACCOUNT_QUERY_BYTE_BOUND")
        capture = {
            "format": "qh-paper-account-capture-1",
            "owner_id": self.user.id,
            "operation_id": self.operation_id,
            "profile_revision": self.profile["revision"],
            "profile_digest": digest(canonical(self.profile)),
            "provider": request.provider,
            "host": request.host,
            "method": "GET",
            "target": request.target,
            "status": response.status,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "raw_digest": self.access.objects.publish(response.body).digest,
            "evidence_mode": self.access.read_evidence_mode,
        }
        self.captures.append(self.access.objects.publish(canonical(capture)).digest)
        return response


class _ProtocolFixture:
    """Closed in-memory fake server. No sockets, vault or configurable transport."""

    def __init__(
        self,
        config: BrokerConfig,
        intent: OrderIntent,
        cash: str,
        equity: str,
        objects: ImmutableObjectStore,
    ) -> None:
        self.config, self.intent, self.cash, self.equity = config, intent, cash, equity
        self.objects = objects
        self.requests: list[JsonRecord] = []

    def send(self, request: Request) -> Response:
        validate_request(request)
        if len(self.requests) >= 4 or request.provider != self.config.provider:
            raise BrokerError("FIXTURE_PROTOCOL_BOUND")
        value: dict[str, object]
        status = 200
        if request.method == "GET" and request.target == "/v2/account":
            value = {
                "id": self.config.account_id,
                "currency": "USD",
                "cash": self.cash,
                "equity": self.equity,
                "status": "ACTIVE",
                "trading_blocked": False,
                "account_blocked": False,
            }
        elif (
            request.method == "GET"
            and request.target == "/v2/assets/" + self.intent.instrument
        ):
            value = {
                "symbol": self.intent.instrument,
                "class": "us_equity",
                "status": "active",
                "tradable": True,
            }
        elif request.method == "GET" and request.target == "/v3/accounts":
            value = {"accounts": [{"id": self.config.account_id}]}
        elif (
            request.method == "GET"
            and request.target == "/v3/accounts/" + self.config.account_id + "/summary"
        ):
            value = {
                "account": {
                    "id": self.config.account_id,
                    "currency": "USD",
                    "balance": self.cash,
                    "NAV": self.equity,
                }
            }
        elif (
            request.method == "GET"
            and request.target
            == "/v3/accounts/"
            + self.config.account_id
            + "/instruments?instruments="
            + self.intent.instrument
        ):
            value = {
                "instruments": [
                    {
                        "name": self.intent.instrument,
                        "type": "CURRENCY",
                        "tradeUnitsPrecision": 0,
                        "displayPrecision": 5,
                        "minimumTradeSize": "1",
                        "maximumOrderUnits": "1000000",
                    }
                ]
            }
        elif (
            request.method == "POST"
            and request.provider == "ALPACA"
            and request.target == "/v2/orders"
        ):
            body = _record(request.body or b"{}")
            value = {
                **body,
                "id": str(uuid5(NAMESPACE_OID, self.intent.client_order_id)),
                "filled_qty": "0",
                "filled_avg_price": None,
                "status": "new",
                "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
            status = 201
        elif (
            request.method == "POST"
            and request.provider == "OANDA"
            and request.target == "/v3/accounts/" + self.config.account_id + "/orders"
        ):
            order = _record(canonical(_record(request.body or b"{}")["order"]))
            value = {
                "orderCreateTransaction": {
                    **order,
                    "id": "101",
                    "accountID": self.config.account_id,
                    "time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
            }
            status = 201
        else:
            raise BrokerError("FIXTURE_PROTOCOL_REFUSED")
        raw = canonical(value)
        self.requests.append(
            {
                "provider": request.provider,
                "method": request.method,
                "target": request.target,
                "request_digest": self.objects.publish(request.body or b"").digest,
                "response_digest": self.objects.publish(raw).digest,
                "status": status,
            }
        )
        return Response(status, raw)


class _RetainedAccount:
    """Read-only parser input, incapable of HTTP or credential consumption."""

    def __init__(self, rows: list[tuple[str, Response]]) -> None:
        self.rows = tuple(rows)
        self.cursor = 0

    def send(self, request: Request) -> Response:
        if (
            self.cursor >= len(self.rows)
            or request.method != "GET"
            or request.body is not None
        ):
            raise BrokerError("BROKER_CAPTURE_SEQUENCE")
        target, response = self.rows[self.cursor]
        if request.target != target:
            raise BrokerError("BROKER_CAPTURE_SEQUENCE")
        self.cursor += 1
        return response


class BrokerAccess:
    """External capability is read-only; dry-run mutation always uses a fixed fixture."""

    def __init__(
        self,
        state: AppState,
        paper: PaperAccess,
        objects: ImmutableObjectStore,
        private_root: Path,
        application_root: Path,
        *,
        read_transport: Transport | None = None,
        resource: Callable[
            [User, str], AbstractContextManager[object]
        ] = _resource_missing,
    ) -> None:
        if paper.state is not state or paper.lab.objects is not objects:
            raise BrokerError("BROKER_SHARED_STORES_REQUIRED")
        for path in (private_root, application_root, state.path.parent):
            protection.safe_path(path)
        for public in (application_root.resolve(), state.path.parent.resolve()):
            if private_root.resolve().is_relative_to(public) or public.is_relative_to(
                private_root.resolve()
            ):
                raise VaultError("PRIVATE_ROOT_OVERLAPS_APPLICATION")
        self.state, self.paper, self.objects = state, paper, objects
        self.private_root, self.application_root = (
            private_root / "paper_brokers",
            application_root,
        )
        self.read_transport, self.resource = read_transport, resource
        self.read_evidence_mode = (
            "PRIVATE_PAPER_ACCOUNT_READ"
            if type(read_transport) is FixedPaperHTTPS
            and read_transport.network_enabled
            else "RECORDED_FIXTURE"
        )
        self._storage: CredentialVault | None = None
        self._lock = threading.RLock()
        package = Path(__file__).resolve().parents[1]
        self._implementation = {
            name: (package / name).read_bytes()
            for name in (
                "web/broker_access.py",
                "paper_brokers/clients.py",
                "paper_brokers/common.py",
                "paper_brokers/journal.py",
                "paper_brokers/transport.py",
            )
        }
        self.journal = SubmissionJournal(state.path.parent / "paper-brokers.sqlite3")
        with state.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS qhb_profiles(owner_id INTEGER NOT NULL,provider TEXT NOT NULL,revision INTEGER NOT NULL,payload BLOB NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(owner_id,provider,revision));
                CREATE TABLE IF NOT EXISTS qhb_operations(id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL,provider TEXT NOT NULL,kind TEXT NOT NULL,payload BLOB NOT NULL,digest TEXT NOT NULL,started_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS qhb_receipts(operation_id TEXT PRIMARY KEY,payload BLOB NOT NULL,digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS qhb_dry_claims(owner_id INTEGER NOT NULL,provider TEXT NOT NULL,paper_id TEXT NOT NULL,order_id TEXT NOT NULL,operation_id TEXT NOT NULL,PRIMARY KEY(owner_id,provider,paper_id,order_id));
            """)
            for table in (
                "qhb_profiles",
                "qhb_operations",
                "qhb_receipts",
                "qhb_dry_claims",
            ):
                for operation in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable paper broker record'); END"
                    )

    def _actor(self, user: User) -> None:
        with self.state.connection() as db:
            self._actor_db(db, user)

    @staticmethod
    def _actor_db(db: sqlite3.Connection, user: User) -> None:
        actual = db.execute(
            "SELECT username,role FROM users WHERE id=?", (user.id,)
        ).fetchone()
        if (
            actual is None
            or tuple(actual) != (user.username, user.role)
            or user.role != "owner"
        ):
            raise AccessError("Owner role required for paper broker operations")

    def _vault(self) -> CredentialVault:
        with self._lock:
            if self._storage is None:
                self._storage = CredentialVault(
                    self.private_root, self.application_root
                )
            return self._storage

    def _read_object(self, identity: str, maximum: int = 2_097_152) -> bytes:
        path = self.objects.object_path(identity)
        protection.safe_path(path)
        with path.open("rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise BrokerError("BROKER_OBJECT_TYPE")
            raw = source.read(maximum + 1)
        if len(raw) > maximum or digest(raw) != identity:
            raise BrokerError("BROKER_OBJECT_BOUND_OR_DIGEST")
        return raw

    def _code_evidence(self) -> str:
        files = {
            name: self.objects.publish(raw).digest
            for name, raw in self._implementation.items()
        }
        return self.objects.publish(
            canonical(
                {
                    "format": "qh-paper-broker-code-1",
                    "files": files,
                    "environment_digest": self.paper.lab.environment_digest,
                }
            )
        ).digest

    @staticmethod
    def _profile_row(
        db: sqlite3.Connection, owner: int, provider: str
    ) -> JsonRecord | None:
        row = db.execute(
            "SELECT revision,payload,digest FROM qhb_profiles WHERE owner_id=? AND provider=? ORDER BY revision DESC LIMIT 1",
            (owner, provider),
        ).fetchone()
        if row is None:
            return None
        raw = row["payload"]
        if (
            not isinstance(raw, bytes)
            or len(raw) > 4096
            or digest(raw) != row["digest"]
        ):
            raise BrokerError("PROFILE_INTEGRITY")
        result = _record(raw)
        if (
            set(result)
            != {
                "owner_id",
                "provider",
                "revision",
                "account_id",
                "enabled",
                "vault_slot",
                "credential_source",
                "paper_only_confirmed",
            }
            or result.get("owner_id") != owner
            or result.get("provider") != provider
            or type(result.get("revision")) is not int
            or result.get("revision") != row["revision"]
            or not 1 <= row["revision"] <= 64
            or type(result.get("enabled")) is not bool
            or result.get("paper_only_confirmed") is not True
            or result.get("credential_source")
            != ("ALPACA_PAPER" if provider == "ALPACA" else "OANDA_PRACTICE")
        ):
            raise BrokerError("PROFILE_BINDING")
        identifier(result["vault_slot"], r"profile_[a-f0-9]{32}")
        identifier(
            result["account_id"],
            r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
            if provider == "ALPACA"
            else r"[0-9]{3}-[0-9]{3}-[0-9]{6,12}-[0-9]{3}",
        )
        return result

    def _profile(self, user: User, provider: str) -> JsonRecord | None:
        with self.state.connection() as db:
            return self._profile_row(db, user.id, _provider(provider))

    def status(self, user: User) -> list[JsonRecord]:
        self._actor(user)
        output: list[JsonRecord] = []
        for provider in PROVIDERS:
            profile = self._profile(user, provider)
            output.append(
                {
                    "provider": provider,
                    "mode": "BROKER_PAPER",
                    "configured": profile is not None,
                    "revision": profile["revision"] if profile else 0,
                    "enabled": profile["enabled"] if profile else False,
                    "account_masked": "****" + cast(str, profile["account_id"])[-4:]
                    if profile
                    else None,
                    "secret_masked": "********" if profile else None,
                    "credential_purpose": "PAPER_OR_READ_ONLY",
                    "credential_origin_evidence": "OWNER_ASSERTED_PAPER_ONLY"
                    if profile
                    else None,
                    "authenticated_smoke": "BLOCKED_EXTERNAL_OR_NOT_YET_TESTED",
                    "network_orders_enabled": False,
                    "read_test_configured": self.read_transport is not None,
                }
            )
        return output

    def configure(
        self,
        user: User,
        provider: str,
        *,
        account_id: str,
        key: str,
        secret: str | None,
        credential_source: str,
        paper_only_confirmed: bool,
        expected_revision: int,
    ) -> JsonRecord:
        self._actor(user)
        _provider(provider)
        config = BrokerConfig(
            provider, str(user.id), account_id, PaperCredentials(key, secret)
        )
        config.validate()
        if (
            credential_source
            != ("ALPACA_PAPER" if provider == "ALPACA" else "OANDA_PRACTICE")
            or paper_only_confirmed is not True
            or type(expected_revision) is not int
            or not 0 <= expected_revision < 63
        ):
            raise BrokerError("EXPLICIT_PAPER_ORIGIN_AND_REVISION_REQUIRED")
        slot = "profile_" + uuid4().hex
        profile: JsonRecord = {
            "provider": provider,
            "owner_id": user.id,
            "account_id": account_id,
            "revision": expected_revision + 1,
            "enabled": True,
            "vault_slot": slot,
            "credential_source": credential_source,
            "paper_only_confirmed": True,
        }
        with self._lock:
            current = self._profile(user, provider)
            if (current["revision"] if current else 0) != expected_revision:
                raise BrokerError("STALE_PAPER_PROFILE")
            self._vault().set_secret(
                "BROKER_" + provider,
                "owner_" + str(user.id),
                slot,
                canonical(
                    {
                        "key": key,
                        "secret": secret,
                        "account_id": account_id,
                        "provider": provider,
                        "credential_source": credential_source,
                    }
                ),
            )
            self._append_profile(user, profile, expected_revision)
        return next(row for row in self.status(user) if row["provider"] == provider)

    def _append_profile(self, user: User, profile: JsonRecord, previous: int) -> None:
        self._actor(user)
        provider = cast(str, profile["provider"])
        raw = canonical(profile)
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._actor_db(db, user)
            current = self._profile_row(db, user.id, provider)
            if (current["revision"] if current else 0) != previous:
                raise BrokerError("STALE_PAPER_PROFILE")
            heads = db.execute(
                "SELECT DISTINCT owner_id,provider FROM qhb_profiles"
            ).fetchall()
            enabled = 0
            for head in heads:
                saved = self._profile_row(db, head[0], head[1])
                if saved is None:
                    raise BrokerError("PROFILE_BINDING")
                enabled += int(saved["enabled"] is True)
            enabled += int(profile["enabled"] is True) - int(
                current is not None and current["enabled"] is True
            )
            if (
                db.execute("SELECT count(*) FROM qhb_profiles").fetchone()[0]
                + 1
                + enabled
                > MAX_PROFILES
                or len(raw) > 4096
            ):
                raise BrokerError("PAPER_PROFILE_CAPACITY")
            db.execute(
                "INSERT INTO qhb_profiles VALUES(?,?,?,?,?)",
                (user.id, provider, profile["revision"], raw, digest(raw)),
            )

    def revoke(
        self, user: User, provider: str, *, expected_revision: int
    ) -> JsonRecord:
        self._actor(user)
        with self._lock:
            current = self._profile(user, provider)
            if (
                current is None
                or type(expected_revision) is not int
                or current["revision"] != expected_revision
                or expected_revision >= 64
            ):
                raise BrokerError("STALE_PAPER_PROFILE")
            if current["enabled"] is False:
                return next(
                    row for row in self.status(user) if row["provider"] == provider
                )
            self._append_profile(
                user,
                {**current, "revision": expected_revision + 1, "enabled": False},
                expected_revision,
            )
            self._vault().revoke(
                "BROKER_" + provider,
                "owner_" + str(user.id),
                cast(str, current["vault_slot"]),
            )
        return next(row for row in self.status(user) if row["provider"] == provider)

    def _begin(
        self,
        user: User,
        provider: str,
        kind: str,
        request: JsonRecord,
        *,
        identity: str | None = None,
    ) -> tuple[str, bool]:
        self._actor(user)
        operation_id = identity or "BROP-" + uuid4().hex
        raw = canonical(
            {
                "owner_id": user.id,
                "provider": provider,
                "kind": kind,
                "request": request,
            }
        )
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._actor_db(db, user)
            old = db.execute(
                "SELECT owner_id,payload FROM qhb_operations WHERE id=?",
                (operation_id,),
            ).fetchone()
            if old is not None:
                if old["owner_id"] != user.id or old["payload"] != raw:
                    raise BrokerError("CONFLICTING_PAPER_OPERATION")
                return operation_id, False
            if (
                db.execute("SELECT count(*) FROM qhb_operations").fetchone()[0]
                >= MAX_OPERATIONS
                or len(raw) > 16_384
            ):
                raise BrokerError("BROKER_OPERATION_CAPACITY")
            db.execute(
                "INSERT INTO qhb_operations VALUES(?,?,?,?,?,?,?)",
                (
                    operation_id,
                    user.id,
                    provider,
                    kind,
                    raw,
                    digest(raw),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return operation_id, True

    def _finish(self, operation_id: str, result: JsonRecord) -> None:
        raw = canonical(result)
        if len(raw) > 16_384:
            raise BrokerError("BROKER_RESULT_BOUND")
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT digest FROM qhb_operations WHERE id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise BrokerError("BROKER_OPERATION_MISSING")
            envelope = canonical(
                {
                    "request_digest": row["digest"],
                    "finished_at": datetime.now(UTC).isoformat(),
                    "result": result,
                }
            )
            db.execute(
                "INSERT INTO qhb_receipts VALUES(?,?,?)",
                (operation_id, envelope, digest(envelope)),
            )

    def get(self, user: User, operation_id: str) -> JsonRecord:
        self._actor(user)
        with self.state.connection() as db:
            row = db.execute(
                "SELECT * FROM qhb_operations WHERE id=? AND owner_id=?",
                (operation_id, user.id),
            ).fetchone()
            receipt = db.execute(
                "SELECT * FROM qhb_receipts WHERE operation_id=?", (operation_id,)
            ).fetchone()
        if row is None:
            raise AccessError("Paper broker operation unavailable")
        if (
            not isinstance(row["payload"], bytes)
            or len(row["payload"]) > 16_384
            or digest(row["payload"]) != row["digest"]
        ):
            raise BrokerError("BROKER_OPERATION_INTEGRITY")
        request = _record(row["payload"])
        if (
            request.get("owner_id") != user.id
            or request.get("provider") != row["provider"]
            or request.get("kind") != row["kind"]
        ):
            raise BrokerError("BROKER_OPERATION_BINDING")
        result: JsonRecord = {
            "status": "UNKNOWN",
            "reason": "INTERRUPTED_OR_RUNNING_NO_AUTOMATIC_RETRY",
        }
        if receipt:
            if (
                not isinstance(receipt["payload"], bytes)
                or len(receipt["payload"]) > 17_000
                or digest(receipt["payload"]) != receipt["digest"]
            ):
                raise BrokerError("BROKER_RECEIPT_INTEGRITY")
            envelope = _record(receipt["payload"])
            if envelope.get("request_digest") != row["digest"] or not isinstance(
                envelope.get("result"), dict
            ):
                raise BrokerError("BROKER_RECEIPT_BINDING")
            result = cast(JsonRecord, envelope["result"])
        return {
            "operation_id": operation_id,
            **request,
            "result": result,
            "started_at": row["started_at"],
            "status_authority": "OPERATIONAL_JOURNAL",
            "network_orders_enabled": False,
        }

    def operations(self, user: User) -> list[JsonRecord]:
        self._actor(user)
        with self.state.connection() as db:
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM qhb_operations WHERE owner_id=? ORDER BY rowid DESC LIMIT 100",
                    (user.id,),
                )
            ]
        return [self.get(user, identity) for identity in ids]

    def _verify_protocol(
        self,
        user: User,
        operation: JsonRecord,
        proof: JsonRecord,
        context: JsonRecord,
        snapshot: JsonRecord,
    ) -> None:
        """Check retained fixture semantics and journal identity; never resend."""
        provider, operation_id = (
            cast(str, operation["provider"]),
            cast(str, operation["operation_id"]),
        )
        config = _fixture_config(provider, user.id)
        reservations = snapshot.get("reservations")
        if (
            not isinstance(reservations, list)
            or len(reservations) != 1
            or not isinstance(reservations[0], dict)
        ):
            raise BrokerError("BROKER_RESERVATION_BINDING")
        reservation = reservations[0]
        book = cast(JsonRecord, snapshot["book"])
        specs = cast(list[JsonRecord], book["instruments"])
        if (
            len(specs) != 1
            or specs[0]["instrument_id"] != reservation["instrument_id"]
            or reservation["strategy_id"] != context["strategy_id"]
        ):
            raise BrokerError("BROKER_RESERVATION_BINDING")
        symbol = "QHSYNTH" if provider == "ALPACA" else cast(str, specs[0]["symbol"])
        if proof.get("symbol_mapping") != {
            "canonical": specs[0]["symbol"],
            "offline_protocol": symbol,
        }:
            raise BrokerError("BROKER_SYMBOL_BINDING")
        client_id = (
            "DRY-"
            + digest(
                canonical(
                    [user.id, provider, context["paper_id"], reservation["order_id"]]
                )
            ).split(":")[1][:32]
        )
        intent = OrderIntent(
            client_id,
            symbol,
            Decimal(cast(str, reservation["remaining"])),
            cast(str, reservation["side"]),
            "MARKET",
            "DAY" if provider == "ALPACA" else "FOK",
        )
        intent.validate(provider)
        with self.state.connection() as db:
            claim = db.execute(
                "SELECT operation_id FROM qhb_dry_claims WHERE owner_id=? AND provider=? AND paper_id=? AND order_id=?",
                (user.id, provider, context["paper_id"], reservation["order_id"]),
            ).fetchone()
        submission = _record(canonical(asdict(self.journal.load(config, operation_id))))
        result = cast(JsonRecord, operation["result"])
        if (
            claim is None
            or claim[0] != operation_id
            or proof.get("submission") != submission
            or self.journal.request(config, operation_id)
            != _record(action_bytes("SUBMIT", intent, None))
            or (
                result.get("status") != "FAILED"
                and (
                    result.get("submission") != submission
                    or result.get("status") != submission["state"]
                    or result.get("paper_context") != context
                )
            )
        ):
            raise BrokerError("BROKER_JOURNAL_BINDING")
        contracts = proof.get("http_fixture_contracts")
        base = "/v3/accounts/" + config.account_id
        sequence = (
            [
                ("GET", "/v2/account"),
                ("GET", "/v2/assets/" + symbol),
                ("POST", "/v2/orders"),
            ]
            if provider == "ALPACA"
            else [
                ("GET", "/v3/accounts"),
                ("GET", base + "/summary"),
                ("GET", base + "/instruments?instruments=" + symbol),
                ("POST", base + "/orders"),
            ]
        )
        if (
            not isinstance(contracts, list)
            or not 1 <= len(contracts) <= len(sequence)
            or (
                submission["state"] == "ACKNOWLEDGED"
                and len(contracts) != len(sequence)
            )
        ):
            raise BrokerError("BROKER_CONTRACT_BOUND")
        cash = cast(list[JsonRecord], book["cash"])[0]["amount"]
        for index, item in enumerate(contracts):
            method, target = sequence[index]
            if (
                not isinstance(item, dict)
                or set(item)
                != {
                    "provider",
                    "method",
                    "target",
                    "request_digest",
                    "response_digest",
                    "status",
                }
                or item["provider"] != provider
                or item["method"] != method
                or item["target"] != target
                or type(item["status"]) is not int
                or item["status"] != (201 if method == "POST" else 200)
            ):
                raise BrokerError("BROKER_CONTRACT_BINDING")
            request_raw = self._read_object(cast(str, item["request_digest"]), 16_384)
            response = _record(
                self._read_object(cast(str, item["response_digest"]), 16_384)
            )
            expected: JsonRecord
            if method == "GET":
                if request_raw != b"":
                    raise BrokerError("BROKER_CONTRACT_BINDING")
                if target == "/v2/account":
                    expected = {
                        "id": config.account_id,
                        "currency": "USD",
                        "cash": cash,
                        "equity": snapshot["equity"],
                        "status": "ACTIVE",
                        "trading_blocked": False,
                        "account_blocked": False,
                    }
                elif target.startswith("/v2/assets/"):
                    expected = {
                        "symbol": symbol,
                        "class": "us_equity",
                        "status": "active",
                        "tradable": True,
                    }
                elif target == "/v3/accounts":
                    expected = {"accounts": [{"id": config.account_id}]}
                elif target.endswith("/summary"):
                    expected = {
                        "account": {
                            "id": config.account_id,
                            "currency": "USD",
                            "balance": cash,
                            "NAV": snapshot["equity"],
                        }
                    }
                else:
                    expected = {
                        "instruments": [
                            {
                                "name": symbol,
                                "type": "CURRENCY",
                                "tradeUnitsPrecision": 0,
                                "displayPrecision": 5,
                                "minimumTradeSize": "1",
                                "maximumOrderUnits": "1000000",
                            }
                        ]
                    }
            elif provider == "ALPACA":
                body: JsonRecord = {
                    "symbol": symbol,
                    "qty": str(intent.quantity),
                    "side": intent.side.lower(),
                    "type": "market",
                    "time_in_force": "day",
                    "client_order_id": client_id,
                    "order_class": "simple",
                    "extended_hours": False,
                }
                if _record(request_raw) != body:
                    raise BrokerError("BROKER_REQUEST_BINDING")
                expected = {
                    **body,
                    "id": str(uuid5(NAMESPACE_OID, client_id)),
                    "filled_qty": "0",
                    "filled_avg_price": None,
                    "status": "new",
                    "created_at": timestamp(response.get("created_at")),
                }
                if submission["broker_order_id"] != expected["id"]:
                    raise BrokerError("BROKER_ACK_BINDING")
            else:
                units = (
                    str(intent.quantity)
                    if intent.side == "BUY"
                    else str(intent.quantity.copy_negate())
                )
                order: JsonRecord = {
                    "instrument": symbol,
                    "units": units,
                    "type": "MARKET",
                    "timeInForce": "FOK",
                    "positionFill": "REDUCE_FIRST",
                    "clientExtensions": {"id": client_id},
                }
                if _record(request_raw) != {"order": order}:
                    raise BrokerError("BROKER_REQUEST_BINDING")
                transaction = response.get("orderCreateTransaction")
                if not isinstance(transaction, dict):
                    raise BrokerError("BROKER_ACK_BINDING")
                expected = {
                    "orderCreateTransaction": {
                        **order,
                        "id": "101",
                        "accountID": config.account_id,
                        "time": timestamp(transaction.get("time")),
                    }
                }
                if submission["broker_order_id"] != "101":
                    raise BrokerError("BROKER_ACK_BINDING")
            if response != expected:
                raise BrokerError("BROKER_RESPONSE_BINDING")

    def evidence(self, user: User, operation_id: str) -> JsonRecord:
        """Verify retained bytes under shared resource admission, without resending."""
        self._actor(user)
        with self.resource(user, "BROKER_EVIDENCE_READ"):
            operation = self.get(user, operation_id)
            result = cast(JsonRecord, operation["result"])
            verified: list[str] = []
            proof_digest = result.get("proof_digest")
            captures = result.get("capture_digests", [])
            if (
                operation["kind"] == "OFFLINE_PROTOCOL"
                and (
                    result.get("status") in {"ACKNOWLEDGED", "REJECTED"}
                    or "submission" in result
                )
                and not isinstance(proof_digest, str)
            ) or (
                operation["kind"] == "ACCOUNT_READ"
                and result.get("status") == "VERIFIED_ACCOUNT_READ"
                and (
                    not isinstance(captures, list)
                    or len(captures) != (1 if operation["provider"] == "ALPACA" else 2)
                )
            ):
                raise BrokerError("BROKER_REQUIRED_EVIDENCE_MISSING")
            if proof_digest is not None:
                if not isinstance(proof_digest, str):
                    raise BrokerError("BROKER_PROOF_BINDING")
                proof_raw = self._read_object(proof_digest)
                if len(proof_raw) > 2_097_152:
                    raise BrokerError("BROKER_EVIDENCE_BOUND")
                proof = _record(proof_raw)
                if (
                    proof.get("operation_id") != operation_id
                    or proof.get("owner_id") != user.id
                    or proof.get("provider") != operation["provider"]
                    or proof.get("format") != "qh-offline-protocol-proof-1"
                ):
                    raise BrokerError("BROKER_PROOF_BINDING")
                context, snapshot = proof.get("context"), proof.get("snapshot")
                if (
                    not isinstance(context, dict)
                    or not isinstance(snapshot, dict)
                    or digest(canonicalize_json(snapshot))
                    != context.get("snapshot_digest")
                    or context.get("paper_id")
                    != cast(JsonRecord, operation["request"]).get("paper_id")
                    or context.get("workflow_revision")
                    != cast(JsonRecord, operation["request"]).get("workflow_revision")
                ):
                    raise BrokerError("BROKER_SNAPSHOT_BINDING")
                report = _record(self._read_object(cast(str, context["report_digest"])))
                if (
                    report.get("snapshot") != snapshot
                    or report.get("job_id") != context["paper_id"]
                    or snapshot.get("owner_id") != str(user.id)
                ):
                    raise BrokerError("BROKER_REPORT_BINDING")
                try:
                    historical = self.paper.execution_receipt(
                        user,
                        cast(str, context["paper_id"]),
                        workflow_revision=cast(int, context["workflow_revision"]),
                    )
                except Exception:
                    raise BrokerError("BROKER_HISTORICAL_RECEIPT_BINDING") from None
                if historical != {"context": context, "snapshot": snapshot}:
                    raise BrokerError("BROKER_HISTORICAL_RECEIPT_BINDING")
                self._verify_protocol(user, operation, proof, context, snapshot)
                verified.append(proof_digest)
                implementation = _record(
                    self._read_object(cast(str, proof["implementation_digest"]), 16_384)
                )
                provenance = snapshot.get("provenance")
                if (
                    not isinstance(provenance, dict)
                    or provenance.get("environment_digest")
                    != implementation.get("environment_digest")
                    or provenance.get("experiment_id") != context.get("experiment_id")
                ):
                    raise BrokerError("BROKER_PROVENANCE_BINDING")
                files = implementation.get("files")
                if not isinstance(files, dict) or set(files) != set(
                    self._implementation
                ):
                    raise BrokerError("BROKER_CODE_BINDING")
                for identity in files.values():
                    self._read_object(cast(str, identity), 262_144)
                environment = _record(
                    self._read_object(cast(str, implementation["environment_digest"]))
                )
                if "source_snapshot_digest" in environment:
                    self._read_object(
                        cast(str, environment["source_snapshot_digest"]),
                        64 * 1024 * 1024,
                    )
            if not isinstance(captures, list) or len(captures) > 2:
                raise BrokerError("BROKER_CAPTURE_BOUND")
            total = 0
            retained: list[tuple[str, Response]] = []
            profile: JsonRecord | None = None
            for capture_digest in captures:
                if not isinstance(capture_digest, str):
                    raise BrokerError("BROKER_CAPTURE_BINDING")
                capture = _record(self._read_object(capture_digest, 4096))
                if (
                    capture.get("owner_id") != user.id
                    or capture.get("provider") != operation["provider"]
                    or capture.get("method") != "GET"
                    or capture.get("host") != HOSTS[cast(str, operation["provider"])]
                    or capture.get("operation_id") != operation_id
                    or capture.get("profile_revision")
                    != cast(JsonRecord, operation["request"]).get("profile_revision")
                ):
                    raise BrokerError("BROKER_CAPTURE_BINDING")
                with self.state.connection() as db:
                    saved = db.execute(
                        "SELECT payload,digest FROM qhb_profiles WHERE owner_id=? AND provider=? AND revision=?",
                        (user.id, operation["provider"], capture["profile_revision"]),
                    ).fetchone()
                if (
                    saved is None
                    or not isinstance(saved[0], bytes)
                    or len(saved[0]) > 4096
                    or digest(saved[0]) != saved[1]
                    or saved[1] != capture.get("profile_digest")
                ):
                    raise BrokerError("BROKER_CAPTURE_PROFILE_BINDING")
                selected = _record(saved[0])
                if (
                    selected.get("owner_id") != user.id
                    or selected.get("provider") != operation["provider"]
                    or selected.get("revision") != capture["profile_revision"]
                    or selected.get("enabled") is not True
                    or (profile is not None and profile != selected)
                ):
                    raise BrokerError("BROKER_CAPTURE_PROFILE_BINDING")
                profile = selected
                expected_targets = (
                    ["/v2/account"]
                    if operation["provider"] == "ALPACA"
                    else [
                        "/v3/accounts",
                        "/v3/accounts/" + cast(str, profile["account_id"]) + "/summary",
                    ]
                )
                if (
                    len(retained) >= len(expected_targets)
                    or capture.get("target") != expected_targets[len(retained)]
                    or type(capture.get("status")) is not int
                ):
                    raise BrokerError("BROKER_CAPTURE_SEQUENCE")
                raw = self._read_object(cast(str, capture["raw_digest"]))
                total += len(raw)
                if total > 2_097_152:
                    raise BrokerError("BROKER_CAPTURE_BOUND")
                retained.append(
                    (
                        expected_targets[len(retained)],
                        Response(cast(int, capture["status"]), raw),
                    )
                )
                if result.get("status") == "VERIFIED_ACCOUNT_READ" and capture.get(
                    "evidence_mode"
                ) != result.get("evidence_mode"):
                    raise BrokerError("BROKER_CAPTURE_MODE_BINDING")
                verified.append(capture_digest)
            if result.get("status") == "VERIFIED_ACCOUNT_READ":
                if profile is None:
                    raise BrokerError("BROKER_CAPTURE_PROFILE_BINDING")
                synthetic = _fixture_config(cast(str, operation["provider"]), user.id)
                config = BrokerConfig(
                    synthetic.provider,
                    synthetic.owner_id,
                    cast(str, profile["account_id"]),
                    synthetic.credentials,
                )
                replay = _RetainedAccount(retained)
                parsed = PaperBroker(
                    config, self.journal, transport=replay
                ).test_connection()
                if _record(canonical(asdict(parsed))) != result.get(
                    "account"
                ) or replay.cursor != len(retained):
                    raise BrokerError("BROKER_CAPTURE_ACCOUNT_BINDING")
            return {
                "operation_id": operation_id,
                "verified_digests": list(verified),
                "evidence_mode": result.get("evidence_mode"),
                "research_approval": False,
                "external_requests": 0,
            }

    def test_connection(
        self, user: User, provider: str, *, expected_revision: int
    ) -> JsonRecord:
        self._actor(user)
        _provider(provider)
        with self.resource(user, "BROKER_ACCOUNT_READ"):
            operation, _ = self._begin(
                user, provider, "ACCOUNT_READ", {"profile_revision": expected_revision}
            )
            captures: list[str] = []
            try:
                profile = self._profile(user, provider)
                if (
                    profile is None
                    or type(expected_revision) is not int
                    or profile["revision"] != expected_revision
                    or profile["enabled"] is not True
                ):
                    raise BrokerError("PAPER_PROFILE_DISABLED_OR_STALE")
                if self.read_transport is None:
                    raise BrokerError("BLOCKED_EXTERNAL_TRANSPORT_NOT_CONFIGURED")
                guarded = _ReadTransport(self, user, profile, operation)

                def consume(raw: bytes) -> JsonRecord:
                    self._actor(user)
                    value = _record(raw)
                    if set(value) != {
                        "key",
                        "secret",
                        "provider",
                        "account_id",
                        "credential_source",
                    } or any(
                        value[k] != profile[k]
                        for k in ("provider", "account_id", "credential_source")
                    ):
                        raise BrokerError("PAPER_SECRET_BINDING")
                    config = BrokerConfig(
                        provider,
                        str(user.id),
                        cast(str, profile["account_id"]),
                        PaperCredentials(
                            cast(str, value["key"]), cast(str | None, value["secret"])
                        ),
                    )
                    client = PaperBroker(config, self.journal, transport=guarded)
                    return _record(canonical(asdict(client.test_connection())))

                try:
                    account = self._vault().with_secret(
                        "BROKER_" + provider,
                        "owner_" + str(user.id),
                        cast(str, profile["vault_slot"]),
                        consume,
                    )
                finally:
                    captures = guarded.captures
                self._actor(user)
                if self._profile(user, provider) != profile:
                    raise BrokerError("PAPER_PROFILE_CHANGED")
                result: JsonRecord = {
                    "status": "VERIFIED_ACCOUNT_READ",
                    "evidence_mode": self.read_evidence_mode,
                    "account": account,
                    "capture_digests": list(captures),
                    "orders_authorized": False,
                }
            except Exception as error:
                result = {
                    "status": "BLOCKED_EXTERNAL"
                    if isinstance(error, BrokerError)
                    and str(error).startswith("BLOCKED_EXTERNAL")
                    else "FAILED",
                    "reason": _failure(error),
                    "capture_digests": list(captures),
                    "orders_authorized": False,
                }
            self._finish(operation, result)
        return self.get(user, operation)

    def dry_run(
        self, user: User, provider: str, paper_id: str, *, expected_revision: int
    ) -> JsonRecord:
        self._actor(user)
        _provider(provider)
        with self.resource(user, "BROKER_OFFLINE_PROTOCOL"):
            identity = (
                "BROP-"
                + digest(
                    canonical([user.id, provider, paper_id, expected_revision])
                ).split(":")[1][:32]
            )
            operation, fresh = self._begin(
                user,
                provider,
                "OFFLINE_PROTOCOL",
                {"paper_id": paper_id, "workflow_revision": expected_revision},
                identity=identity,
            )
            if not fresh:
                return self.get(user, operation)
            proof: str | None = None
            result: JsonRecord
            try:
                context, snapshot = self.paper.execution_snapshot(
                    user, paper_id, expected_revision=expected_revision
                )
                reservation = snapshot.reservations[0]
                spec = next(
                    spec
                    for spec in snapshot.book.instruments
                    if spec.instrument_id == reservation.instrument_id
                )
                if (provider == "ALPACA" and spec.kind not in {"EQUITY", "ETF"}) or (
                    provider == "OANDA" and spec.kind != "FX_SPOT"
                ):
                    raise BrokerError("PAPER_PROVIDER_INSTRUMENT_MISMATCH")
                with self.state.connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    self._actor_db(db, user)
                    previous = db.execute(
                        "SELECT operation_id FROM qhb_dry_claims WHERE owner_id=? AND provider=? AND paper_id=? AND order_id=?",
                        (user.id, provider, paper_id, reservation.order_id),
                    ).fetchone()
                    if previous is not None:
                        raise BrokerError("RESERVATION_ALREADY_DEMONSTRATED_OR_UNKNOWN")
                    db.execute(
                        "INSERT INTO qhb_dry_claims VALUES(?,?,?,?,?)",
                        (user.id, provider, paper_id, reservation.order_id, operation),
                    )
                client_id = (
                    "DRY-"
                    + digest(
                        canonical([user.id, provider, paper_id, reservation.order_id])
                    ).split(":")[1][:32]
                )
                config = _fixture_config(provider, user.id)
                account_id = config.account_id
                # Synthetic equity/ETF names are not broker symbols; this alias
                # exists only in the fixed offline fake server, never in a URL to a broker.
                symbol = "QHSYNTH" if provider == "ALPACA" else spec.symbol
                intent = OrderIntent(
                    client_id,
                    symbol,
                    reservation.remaining,
                    reservation.side,
                    "MARKET",
                    "DAY" if provider == "ALPACA" else "FOK",
                )
                now = datetime.now(UTC)
                authorization = RiskAuthorization(
                    operation,
                    str(user.id),
                    account_id,
                    provider,
                    cast(str, context["experiment_id"]),
                    reservation.strategy_id,
                    digest(action_bytes("SUBMIT", intent, None)),
                    snapshot.revision,
                    now,
                    now + timedelta(seconds=30),
                )
                if (
                    snapshot.book.base_currency != "USD"
                    or len(snapshot.book.cash) != 1
                    or snapshot.book.cash[0].currency != "USD"
                ):
                    raise BrokerError("SINGLE_USD_CASH_ACCOUNT_REQUIRED")
                cash = snapshot.book.cash[0].amount
                wire = _ProtocolFixture(
                    config, intent, str(cash), str(snapshot.equity), self.objects
                )
                client = PaperBroker(config, self.journal, transport=wire)
                submission = client.submit(intent, authorization)
                proof = self.objects.publish(
                    _evidence(
                        {
                            "format": "qh-offline-protocol-proof-1",
                            "operation_id": operation,
                            "owner_id": user.id,
                            "provider": provider,
                            "implementation_digest": self._code_evidence(),
                            "context": context,
                            "snapshot": asdict(snapshot),
                            "symbol_mapping": {
                                "canonical": spec.symbol,
                                "offline_protocol": symbol,
                            },
                            "submission": asdict(submission),
                            "http_fixture_contracts": wire.requests,
                        }
                    )
                ).digest
                latest, current = self.paper.execution_snapshot(
                    user, paper_id, expected_revision=expected_revision
                )
                if latest != context or current != snapshot:
                    raise BrokerError("STALE_PAPER_SNAPSHOT")
                result = {
                    "status": submission.state,
                    "mode": "LOCAL_PAPER",
                    "evidence_mode": "SYNTHETIC_PROTOCOL_FIXTURE",
                    "paper_context": context,
                    "proof_digest": proof,
                    "submission": _record(canonical(asdict(submission))),
                    "economic_book_changed": False,
                    "broker_fill_claimed": False,
                    "external_requests": 0,
                }
            except Exception as error:
                result = {
                    "status": "FAILED",
                    "reason": _failure(error),
                    "proof_digest": proof,
                    "mode": "LOCAL_PAPER",
                    "evidence_mode": "SYNTHETIC_PROTOCOL_FIXTURE",
                    "external_requests": 0,
                    "broker_fill_claimed": False,
                }
            self._finish(operation, result)
        return self.get(user, operation)
