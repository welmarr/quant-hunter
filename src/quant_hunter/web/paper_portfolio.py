"""Owned, read-admitted projections of the existing paper journals, not wealth pooling."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from typing import cast

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.simulation import accounting as a
from quant_hunter.simulation import paper_engine as p
from quant_hunter.web import paper_access as workflow
from quant_hunter.web.paper_access import PaperAccess, PaperWorkflowError
from quant_hunter.web.state import AccessError, User

MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_BYTES = 2_000_000
Inspection = Callable[[User], AbstractContextManager[object]]


class PortfolioError(PaperWorkflowError):
    """A fixed, sanitized evidence or bound refusal."""


@dataclass(frozen=True)
class _Report:
    anchor: JsonRecord
    snapshot_digest: str | None
    revision: int | None
    equity: JsonValue
    max_drawdown: JsonValue
    commissions: JsonValue
    slippage: JsonValue


def _stamp(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def _seconds(start: datetime, end: datetime) -> Decimal:
    delta = end - start
    return Decimal(delta.days * 86400 + delta.seconds) + Decimal(
        delta.microseconds
    ) / Decimal(1_000_000)


def _metrics(state: p.PaperSnapshot) -> JsonRecord:
    """Use the accounting valuation, distinguishing stale marks from zero holdings."""
    with localcontext(a.CONTEXT):
        reserved = sum(
            (r.cash for r in state.reservations if r.side == "BUY"), Decimal(0)
        )
        cash = sum((c.amount for c in state.book.cash), Decimal(0))
        try:
            value = a.value_book(
                state.book,
                state.quotes,
                (),
                as_of=state.at,
                max_quote_age_seconds=state.limits.max_quote_age_seconds,
            )
        except a.AccountingError:
            value = None
        positions: list[JsonValue] = []
        weights: list[Decimal] = []
        quotes = {q.instrument_id: q for q in state.quotes}
        for position in state.book.positions:
            quote = quotes.get(position.instrument_id)
            marked = (
                position.quantity * quote.bid
                if value is not None and quote is not None
                else None
            )
            weight = (
                marked / value.equity
                if marked is not None and value is not None and value.equity > 0
                else None
            )
            if weight is not None:
                weights.append(weight)
            positions.append(
                {
                    "instrument_id": position.instrument_id,
                    "quantity": str(position.quantity),
                    "cost_basis": str(position.cost_basis),
                    "bid_marked_value": str(marked) if marked is not None else None,
                    "fraction_of_equity": str(weight) if weight is not None else None,
                    "quote_at": _stamp(quote.at) if quote else None,
                    "quote_available_at": _stamp(quote.available_at) if quote else None,
                    "mark_status": "AVAILABLE" if marked is not None else "UNAVAILABLE",
                }
            )
        return {
            "engine_revision": state.revision,
            "at": _stamp(state.at),
            "base_currency": state.book.base_currency,
            "recorded_equity": str(state.equity),
            "recorded_high_water": str(state.high_water),
            "recorded_drawdown": str(state.drawdown),
            "recorded_max_drawdown": str(state.max_drawdown),
            "cash_balances": [
                {"currency": c.currency, "amount": str(c.amount)}
                for c in state.book.cash
            ],
            "reserved_buy_cash": str(reserved),
            "cash_after_buy_reservations": str(cash - reserved),
            "positions": positions,
            "valuation_status": "AVAILABLE" if value else "UNAVAILABLE",
            "valuation_reason": None if value else "MARKS_NOT_USABLE_AT_RECORDED_TIME",
            "valuation": workflow._json(value) if value else None,
            "largest_position_fraction_of_equity": str(max(weights, default=Decimal(0)))
            if value and value.equity > 0
            else None,
            "concentration_status": "AVAILABLE"
            if value and value.equity > 0
            else "UNAVAILABLE",
            "commissions": str(
                sum((f.commission for f in state.book.fills), Decimal(0))
            ),
            "adverse_slippage": str(
                sum((f.adverse_slippage for f in state.book.fills), Decimal(0))
            ),
        }


class PaperPortfolio:
    """Inspection callback is mandatory and must reserve the shared read resource.

    Economic history is replayed by the existing native engine functions. This
    adapter performs no command submission, publication or research transition.
    """

    def __init__(self, access: PaperAccess, *, inspection: Inspection) -> None:
        self.access = access
        self.inspection = inspection

    def _owns(self, user: User, session_id: str | None = None) -> None:
        with self.access.state.connection() as db:
            self.access._actor(db, user, mutation=False)
            if (
                session_id is not None
                and db.execute(
                    "SELECT 1 FROM paper_jobs WHERE id=? AND owner_id=?",
                    (session_id, user.id),
                ).fetchone()
                is None
            ):
                raise AccessError("Paper session unavailable")

    @staticmethod
    def _event_budget(db: sqlite3.Connection, session_id: str) -> None:
        # Check lengths before fetching any untrusted payload, including the
        # mutable cached head. Canonical workflow writes already enforce4096.
        head = db.execute(
            "SELECT length(payload) FROM paper_jobs WHERE id=?", (session_id,)
        ).fetchone()
        sizes = [
            int(row[0])
            for row in db.execute(
                "SELECT length(payload) FROM paper_events WHERE job_id=? LIMIT 601",
                (session_id,),
            )
        ]
        if (
            head is None
            or head[0] > workflow.MAX_EVENT_BYTES
            or not 1 <= len(sizes) <= 600
            or any(size > workflow.MAX_EVENT_BYTES for size in sizes)
        ):
            raise PortfolioError("PORTFOLIO_EVENT_BOUND")

    def list_sessions(self, user: User) -> list[JsonRecord]:
        self._owns(user)
        with self.inspection(user), self.access.state.connection() as db:
            db.execute("BEGIN")
            self.access._actor(db, user, mutation=False)
            ids = [
                str(row[0])
                for row in db.execute(
                    "SELECT id FROM paper_jobs WHERE owner_id=? ORDER BY rowid DESC LIMIT 33",
                    (user.id,),
                )
            ]
            if len(ids) > 32:
                raise PortfolioError("PORTFOLIO_SESSION_BOUND")
            result = []
            for identity in ids:
                self._event_budget(db, identity)
                row = self.access._load(db, identity, user.id)
                result.append(
                    {
                        key: row[key]
                        for key in (
                            "id",
                            "status",
                            "revision",
                            "experiment_id",
                            "report_digest",
                            "cursor",
                            "bars",
                        )
                    }
                    | {
                        "inspection": "VERIFIED_WORKFLOW_CHAIN_ONLY; NOT_FRESH_VALUATION",
                        "evidence_mode": "SYNTHETIC",
                    }
                )
            return result

    def get(self, user: User, session_id: str) -> JsonRecord:
        self._owns(user, session_id)
        with self.inspection(user):
            try:
                return self._get(user, session_id)
            except AccessError, PortfolioError:
                raise
            except Exception:
                raise PortfolioError("PORTFOLIO_EVIDENCE_UNAVAILABLE") from None

    def _history(
        self, user: User, session_id: str
    ) -> tuple[JsonRecord, str, list[tuple[JsonRecord, str]]]:
        with self.access.state.connection() as db:
            db.execute("BEGIN")
            self.access._actor(db, user, mutation=False)
            self._event_budget(db, session_id)
            head = self.access._load(db, session_id, user.id)
            events = [
                (workflow._decode(bytes(row[0])), str(row[1]))
                for row in db.execute(
                    "SELECT payload,digest FROM paper_events WHERE job_id=? ORDER BY sequence LIMIT 601",
                    (session_id,),
                )
            ]
        if not 1 <= len(events) <= 600:
            raise PortfolioError("PORTFOLIO_EVENT_BOUND")
        return head, events[-1][1], events

    def _reports(
        self, head: JsonRecord, events: list[tuple[JsonRecord, str]]
    ) -> list[_Report]:
        reports: list[_Report] = []
        seen: dict[str, tuple[JsonValue, JsonValue]] = {}
        total = 0
        previous_cursor = previous_revision = 0
        for event, event_digest in events:
            if any(
                event[key] != head[key]
                for key in ("configuration", "configuration_digest")
            ) or event["experiment_id"] not in (None, head["experiment_id"]):
                raise PortfolioError("PORTFOLIO_EVENT_IDENTITY")
            digest = event["report_digest"]
            if digest is None:
                continue
            if not isinstance(digest, str):
                raise PortfolioError("PORTFOLIO_REPORT_IDENTITY")
            if digest in seen:
                if digest != reports[-1].anchor["report_digest"]:
                    raise PortfolioError("PORTFOLIO_REPORT_ROLLBACK")
                if seen[digest] != (event["cursor"], event["experiment_id"]):
                    raise PortfolioError("PORTFOLIO_REPEATED_REPORT_BINDING")
                continue
            seen[digest] = (event["cursor"], event["experiment_id"])
            total += self.access.lab.objects.get(digest).byte_size
            if total > MAX_REPORT_BYTES:
                raise PortfolioError("PORTFOLIO_REPORT_BUDGET")
            report = self.access._object(digest)
            cursor = report.get("completed_bars")
            if (
                report.get("format") != "v0-paper-report-1"
                or report.get("job_id") != head["id"]
                or report.get("experiment_id") != head["experiment_id"]
                or event["experiment_id"] != head["experiment_id"]
                or report.get("evidence_mode") != "SYNTHETIC"
                or type(cursor) is not int
                or cursor != event["cursor"]
                or not previous_cursor <= cursor <= cast(int, head["bars"])
                or report.get("scientific_disposition")
                != ("FAILED" if report.get("error") else "INCONCLUSIVE")
            ):
                raise PortfolioError("PORTFOLIO_REPORT_BINDING")
            previous_cursor = cursor
            snapshot = report.get("snapshot")
            revision = None
            if snapshot is not None:
                if (
                    not isinstance(snapshot, dict)
                    or type(snapshot.get("revision")) is not int
                ):
                    raise PortfolioError("PORTFOLIO_SNAPSHOT_SHAPE")
                revision = cast(int, snapshot["revision"])
                if not previous_revision <= revision <= p.MAX_COMMANDS:
                    raise PortfolioError("PORTFOLIO_REPORT_ORDER")
                previous_revision = revision
            elif not report.get("error"):
                raise PortfolioError("PORTFOLIO_UNEXPLAINED_MISSING_SNAPSHOT")
            reports.append(
                _Report(
                    {
                        "report_digest": digest,
                        "workflow_revision": event["revision"],
                        "event_digest": event_digest,
                        "completed_bars": cursor,
                        "engine_revision": revision,
                    },
                    workflow._hash(canonicalize_json(snapshot))
                    if snapshot is not None
                    else None,
                    revision,
                    report.get("equity"),
                    report.get("max_drawdown"),
                    report.get("commissions"),
                    report.get("adverse_slippage"),
                )
            )
        if reports and reports[-1].anchor["report_digest"] != head["report_digest"]:
            raise PortfolioError("PORTFOLIO_REPORT_ROLLBACK")
        return reports

    def _get(self, user: User, session_id: str) -> JsonRecord:
        head, event_digest, events = self._history(user, session_id)
        run, fixture = self.access._binding(head) if head["experiment_id"] else ({}, {})
        reports = self._reports(head, events)
        output: JsonRecord = {
            "format": "v0-single-paper-portfolio-1",
            "session_id": session_id,
            "workflow_status": head["status"],
            "workflow_revision": head["revision"],
            "workflow_event_digest": event_digest,
            "experiment_id": head["experiment_id"],
            "evidence_mode": "SYNTHETIC",
            "scientific_disposition": "FAILED"
            if run.get("evaluation_outcome") == "FAILED"
            else "INCONCLUSIVE",
            "network_enabled": False,
            "scope": "ONE_INDEPENDENT_SESSION",
            "availability": "UNAVAILABLE",
            "reason": "NO_RECORDED_ACCOUNT_SNAPSHOT",
            "current": None,
            "timeline": [],
            "drawdown_duration": None,
            "report_anchors": [r.anchor for r in reports],
            "producer": {
                key: workflow._record(run["bindings"])[key]
                for key in ("code_revision", "environment_digest")
            }
            if run
            else None,
            "limitations": [
                "Synthetic software evidence, not empirical performance or a promotion",
                "Independent session capital is never summed with another session",
                "Timeline is recorded engine equity through the last immutable reported snapshot; no interpolation",
                "Engine equity may retain a previous mark during controls; current valuation separately checks quote freshness",
                "Bid-marked holdings exclude hypothetical liquidation fees; reservation cash is not holdings exposure",
            ],
        }
        revisions = [r.revision for r in reports if r.revision is not None]
        if revisions:
            self._ledger(user, head, run, fixture, reports, output)
        if len(canonicalize_json(output)) > MAX_RESPONSE_BYTES:
            raise PortfolioError("PORTFOLIO_RESPONSE_BOUND")
        return output

    def _ledger(
        self,
        user: User,
        head: JsonRecord,
        run: JsonRecord,
        fixture: JsonRecord,
        reports: list[_Report],
        output: JsonRecord,
    ) -> None:
        session_id = cast(str, head["id"])
        manifest = workflow._record(run["bindings"])
        config = workflow._record(run["configuration"])
        limit = max(r.revision for r in reports if r.revision is not None)
        expected = p.Provenance(
            cast(str, head["experiment_id"]),
            self.access._source(
                cast(str, manifest["environment_digest"]), current=False
            ),
            cast(str, manifest["environment_digest"]),
            cast(str, manifest["configuration_digest"]),
            "SYNTHETIC",
            cast(str, config["mode"]),
        )
        with self.access.engine._connect() as db:
            db.execute("BEGIN")
            genesis_size = db.execute(
                "SELECT length(genesis) FROM accounts WHERE account_id=? AND owner_id=?",
                (session_id, str(user.id)),
            ).fetchone()
            if genesis_size is None or genesis_size[0] > p.MAX_PAYLOAD:
                raise PortfolioError("PORTFOLIO_GENESIS_BOUND")
            sizes = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(length(payload)),0) FROM commands WHERE account_id=?",
                (session_id,),
            ).fetchone()
            if sizes[0] > p.MAX_COMMANDS or sizes[1] > p.MAX_TOTAL_BYTES:
                raise PortfolioError("PORTFOLIO_NATIVE_BOUND")
            current = self.access.engine._load(db, session_id, str(user.id))
            if (
                current.provenance != expected
                or current.book.instruments != (workflow._spec(config, fixture),)
                or current.book.base_currency != "USD"
                or current.limits
                != workflow._limits(config, cast(str, manifest["strategy_id"]))
                or current.inception_equity
                != Decimal(cast(str, config["initial_cash"]))
                or limit > current.revision
            ):
                raise PortfolioError("PORTFOLIO_NATIVE_BINDING")
            genesis = db.execute(
                "SELECT genesis,genesis_hash FROM accounts WHERE account_id=?",
                (session_id,),
            ).fetchone()
            state = cast(p.PaperSnapshot, p._decode(json.loads(bytes(genesis[0]))))
            timeline: list[JsonValue] = []
            peak_at = state.at
            longest = Decimal(0)
            underwater = False
            duration = Decimal(0)
            last_metrics: JsonRecord | None = None

            def observe(
                snapshot: p.PaperSnapshot,
                state_hash: str,
                chain_hash: str,
                command_id: str | None,
            ) -> None:
                nonlocal peak_at, longest, underwater, duration, last_metrics
                matched = [r for r in reports if r.revision == snapshot.revision]
                if matched:
                    digest = workflow._hash(canonicalize_json(workflow._json(snapshot)))
                    with localcontext(a.CONTEXT):
                        commissions = str(
                            sum((f.commission for f in snapshot.book.fills), Decimal(0))
                        )
                        slippage = str(
                            sum(
                                (f.adverse_slippage for f in snapshot.book.fills),
                                Decimal(0),
                            )
                        )
                    if any(
                        r.snapshot_digest != digest
                        or r.equity != str(snapshot.equity)
                        or r.max_drawdown != str(snapshot.max_drawdown)
                        or r.commissions != commissions
                        or r.slippage != slippage
                        for r in matched
                    ):
                        raise PortfolioError("PORTFOLIO_REPORT_NATIVE_DIVERGENCE")
                with localcontext(a.CONTEXT):
                    elapsed = _seconds(peak_at, snapshot.at)
                    if underwater or snapshot.equity < snapshot.high_water:
                        longest = max(longest, elapsed)
                    underwater = snapshot.equity < snapshot.high_water
                    duration = elapsed if underwater else Decimal(0)
                    if not underwater:
                        peak_at = snapshot.at
                timeline.append(
                    {
                        "engine_revision": snapshot.revision,
                        "at": _stamp(snapshot.at),
                        "command_id": command_id,
                        "state_hash": state_hash,
                        "chain_hash": chain_hash,
                        "equity": str(snapshot.equity),
                        "high_water": str(snapshot.high_water),
                        "drawdown": str(snapshot.drawdown),
                        "report_digests": [r.anchor["report_digest"] for r in matched],
                    }
                )
                if snapshot.revision == limit:
                    last_metrics = _metrics(snapshot)

            observe(state, str(genesis[1]), str(genesis[1]), None)
            for entry in db.execute(
                "SELECT * FROM commands WHERE account_id=? AND sequence<=? ORDER BY sequence",
                (session_id, limit),
            ):
                command = cast(
                    p.PaperCommand, p._decode(json.loads(bytes(entry["payload"])))
                )
                state = p._advance(state, command)
                observe(
                    state,
                    str(entry["state_hash"]),
                    str(entry["chain_hash"]),
                    str(entry["command_id"]),
                )
            output.update(
                {
                    "timeline": timeline,
                    "native_head_revision": current.revision,
                    "reported_engine_revision": limit,
                    "unreported_native_revisions": current.revision - limit,
                    "drawdown_duration": {
                        "basis": "RECORDED_COMMAND_OBSERVATIONS",
                        "current_seconds": str(duration),
                        "maximum_seconds": str(longest),
                        "last_peak_at": _stamp(peak_at),
                        "right_censored": underwater,
                    },
                }
            )
            if reports[-1].revision is not None:
                output.update(
                    {
                        "availability": "AVAILABLE",
                        "reason": None,
                        "current": last_metrics,
                    }
                )
            else:
                output["reason"] = "LATEST_FAILURE_REPORT_HAS_NO_ACCOUNT_SNAPSHOT"
