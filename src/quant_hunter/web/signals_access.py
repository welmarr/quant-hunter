"""Owned retained decisions and research observations; no signal execution authority."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING, cast

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.simulation import accounting as a
from quant_hunter.simulation import paper_engine as p
from quant_hunter.web import paper_access as workflow
from quant_hunter.web.paper_access import PaperAccess
from quant_hunter.web.paper_portfolio import Inspection, PaperPortfolio
from quant_hunter.web.state import AccessError, User

if TYPE_CHECKING:
    from quant_hunter.web.pattern_access import PatternAccess

MAX_RESPONSE_BYTES = 2_000_000
MAX_SIGNALS = 100
MAX_JOB_SCAN = 10_000
MAX_JOB_CONFIG_BYTES = 16_384
MAX_TOTAL_CONFIG_BYTES = 32 * 1024**2
_LIMITATIONS = [
    "Retained synthetic software decisions, not current market observations or empirical validation",
    "No frozen forecast horizon or signal expiry exists in this legacy paper profile",
    "Quote freshness is a data check, never a substitute for signal expiry or calibrated probability",
    "Reading never submits an order, creates an experiment, refits a model or promotes a candidate",
]


class SignalError(ValueError):
    """A closed evidence or bound failure, without request or private payloads."""


class SignalChangedError(SignalError):
    """A concurrent source head changed; repeat the read explicitly."""


def _record(value: JsonValue) -> JsonRecord:
    if not isinstance(value, dict):
        raise SignalError("SIGNAL_RECORD_SHAPE")
    return value


def _rows(value: JsonValue, maximum: int = MAX_SIGNALS) -> list[JsonRecord]:
    if not isinstance(value, list) or len(value) > maximum:
        raise SignalError("SIGNAL_LIST_BOUND")
    return [_record(item) for item in value]


def _time(value: JsonValue) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise SignalError("SIGNAL_TIME")
    try:
        result = datetime.fromisoformat(value)
        offset = result.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError
    except ValueError:
        raise SignalError("SIGNAL_TIME") from None
    return result


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _page(limit: int, offset: int, maximum: int) -> None:
    if (
        type(limit) is not int
        or not 1 <= limit <= 25
        or type(offset) is not int
        or not 0 <= offset <= maximum
    ):
        raise SignalError("SIGNAL_PAGE_BOUND")


def _bounded(value: JsonRecord) -> JsonRecord:
    if len(canonicalize_json(value)) > MAX_RESPONSE_BYTES:
        raise SignalError("SIGNAL_RESPONSE_BOUND")
    return value


class SignalsAccess:
    """The trusted host supplies one real shared inspection context and UTC clock.

    Portfolio's internal projection is used only inside that outer reservation;
    its canonical/native replay remains the economic verification authority.
    """

    def __init__(
        self,
        paper: PaperAccess,
        *,
        inspection: Inspection,
        patterns: PatternAccess | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.paper, self.state, self.inspection = paper, paper.state, inspection
        self.portfolio = PaperPortfolio(paper, inspection=inspection)
        self.patterns, self.clock = patterns, clock

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise SignalError("SIGNAL_CLOCK")
        return value.astimezone(UTC)

    def sessions(self, user: User, *, limit: int = 25, offset: int = 0) -> JsonRecord:
        _page(limit, offset, 31)
        # Existing list verifies at most32 operational chains in one reservation.
        rows = self.portfolio.list_sessions(user)
        return {
            "sessions": cast(list[JsonValue], rows[offset : offset + limit]),
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "inspection": "VERIFIED_WORKFLOW_METADATA_ONLY; SELECT_TO_VERIFY_SIGNALS",
        }

    def paper_signals(
        self, user: User, session_id: str, *, limit: int = 25, offset: int = 0
    ) -> JsonRecord:
        _page(limit, offset, MAX_SIGNALS - 1)
        self.portfolio._owns(user, session_id)
        now = self._now()
        with self.inspection(user):
            try:
                return self._paper(user, session_id, now, limit, offset)
            except AccessError, SignalError:
                raise
            except Exception:
                raise SignalError("SIGNAL_EVIDENCE_UNAVAILABLE") from None

    def _paper(
        self, user: User, session_id: str, now: datetime, limit: int, offset: int
    ) -> JsonRecord:
        verified = self.portfolio._get(user, session_id)
        head, event_digest, events = self.portfolio._history(user, session_id)
        if (
            head["revision"] != verified["workflow_revision"]
            or event_digest != verified["workflow_event_digest"]
        ):
            raise SignalChangedError("SIGNAL_WORKFLOW_CHANGED")
        base: JsonRecord = {
            "format": "v0-retained-paper-signals-1",
            "session_id": session_id,
            "workflow_revision": head["revision"],
            "workflow_event_digest": event_digest,
            "workflow_status": head["status"],
            "observed_at": _stamp(now),
            "evidence_mode": "SYNTHETIC",
            "empirical_status": "INCONCLUSIVE",
            "actionable": False,
            "execution_authority": "NONE",
            "limit": limit,
            "offset": offset,
            "total": 0,
            "signals": [],
            "limitations": list(_LIMITATIONS),
        }
        if not head["experiment_id"] or not head["report_digest"]:
            base["availability"] = "NO_RECORDED_DECISIONS"
            return base
        run, fixture = self.paper._binding(head)
        config, manifest = _record(run["configuration"]), _record(run["bindings"])
        if "signal_generation" in config:
            contract = workflow.signal_generation_contract(config)
            if contract != config.get("signal_generation_contract"):
                raise SignalError("SIGNAL_GENERATION_BINDING")
            base["signal_generation_contract"] = contract
            base["limitations"] = [
                _LIMITATIONS[0],
                "The explicitly frozen replay horizon is NOT_EVALUATED; no target outcome or forecast confidence is inferred",
                "Expiry compares the declared simulated timestamps with query UTC; it does not assert a wall-clock cancellation worker or removal of filled positions",
                *_LIMITATIONS[2:],
            ]
        bars = _rows(fixture["bars"])
        report = self.paper._object(cast(str, head["report_digest"]))
        signals = _rows(report["signals"])
        if len(signals) != head["cursor"] or len(signals) > len(bars):
            raise SignalError("SIGNAL_CURSOR_BINDING")
        # Every older retained decision prefix must agree with the latest report.
        # The portfolio already bounds and verifies these exact report objects.
        anchors = _rows(verified["report_anchors"], 600)
        retained: dict[int, JsonRecord] = {}
        for anchor in anchors:
            earlier = self.paper._object(cast(str, anchor["report_digest"]))
            count = earlier["completed_bars"]
            if (
                type(count) is not int
                or not 0 <= count <= len(signals)
                or earlier["signals"] != signals[:count]
            ):
                raise SignalError("SIGNAL_RETAINED_PREFIX")
            event = events[cast(int, anchor["workflow_revision"]) - 1][0]
            recorded_at = _stamp(_time(event["updated_at"]))
            for index in range(count):
                retained.setdefault(
                    index,
                    {
                        "first_report_digest": anchor["report_digest"],
                        "first_workflow_revision": anchor["workflow_revision"],
                        "retained_at": recorded_at,
                    },
                )
        snapshot = (
            _record(report["snapshot"]) if report["snapshot"] is not None else None
        )
        admissions = self._admissions(user, session_id, verified) if snapshot else {}
        shared: JsonRecord = {
            key: manifest[key]
            for key in (
                "strategy_id",
                "strategy_record_digest",
                "source_id",
                "source_record_digest",
                "dataset_id",
                "dataset_record_digest",
                "dataset_digest",
                "configuration_digest",
                "code_revision",
                "environment_digest",
            )
        }
        shared.update(
            {
                "experiment_id": run["experiment_id"],
                "experiment_revision_digest": run["revision_digest"],
                "instrument_id": config["instrument_id"],
                "instrument_revision_digest": config["instrument_revision_digest"],
                "calendar_digest": config["calendar_digest"],
                "instrument": fixture["instrument"],
                "accounting_symbol": config["accounting_symbol"],
                "mode": config["mode"],
                "model_identity_status": "NOT_FITTED; DETERMINISTIC_FROZEN_STRATEGY_RULE",
                "model_ids": [],
            }
        )
        actual = [
            self._signal(
                index,
                signal,
                bars,
                config,
                head,
                snapshot,
                admissions,
                retained[index],
                now,
                verified,
            )
            for index, signal in enumerate(signals)
        ]
        base.update(
            {
                "availability": "VERIFIED_RETAINED_DECISIONS",
                "provenance": shared,
                "report_digest": head["report_digest"],
                "total": len(actual),
                "signals": cast(list[JsonValue], actual[offset : offset + limit]),
                "unreported_native_revisions": verified.get(
                    "unreported_native_revisions"
                ),
                "risk_context": {
                    "scope": "LAST_VERIFIED_REPORTED_SNAPSHOT; ADMISSIONS_ARE_HISTORICAL",
                    "reported_engine_revision": verified.get(
                        "reported_engine_revision"
                    ),
                    "native_head_revision": verified.get("native_head_revision"),
                    "session_control": head["requested"],
                    "killed": snapshot["killed"] if snapshot else None,
                    "snapshot_available": snapshot is not None,
                },
            }
        )
        return _bounded(base)

    def _admissions(
        self, user: User, identity: str, verified: JsonRecord
    ) -> dict[str, p.Admit]:
        with self.paper.engine._connect() as db:
            db.execute("BEGIN")
            sizes = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(length(payload)),0) FROM commands WHERE account_id=?",
                (identity,),
            ).fetchone()
            if sizes[0] > p.MAX_COMMANDS or sizes[1] > p.MAX_TOTAL_BYTES:
                raise SignalError("SIGNAL_NATIVE_BOUND")
            genesis = db.execute(
                "SELECT length(genesis) FROM accounts WHERE account_id=? AND owner_id=?",
                (identity, str(user.id)),
            ).fetchone()
            if genesis is None or genesis[0] > p.MAX_PAYLOAD:
                raise SignalError("SIGNAL_NATIVE_BOUND")
            current = self.paper.engine._load(db, identity, str(user.id))
            if current.revision != verified["native_head_revision"]:
                raise SignalChangedError("SIGNAL_NATIVE_HEAD_CHANGED")
            result = {}
            for row in db.execute(
                "SELECT payload FROM commands WHERE account_id=? AND sequence<=? ORDER BY sequence",
                (identity, verified["reported_engine_revision"]),
            ):
                command = p._decode(json.loads(bytes(row[0])))
                if isinstance(command, p.Admit):
                    result[command.order_id] = command
            return result

    @staticmethod
    def _signal(
        index: int,
        signal: JsonRecord,
        bars: list[JsonRecord],
        config: JsonRecord,
        head: JsonRecord,
        snapshot: JsonRecord | None,
        admissions: dict[str, p.Admit],
        retained: JsonRecord,
        now: datetime,
        verified: JsonRecord,
    ) -> JsonRecord:
        bar = bars[index]
        decision = _time(bar["close_at"])
        last_available = _time(bar["close_available_at"])
        lookback = cast(int, config["lookback"])
        with localcontext(a.CONTEXT):
            bid = Decimal(cast(str, bar["close_bid"]))
            comparison = (
                Decimal(cast(str, bars[index - lookback]["close_bid"]))
                if index >= lookback
                else None
            )
            if comparison is not None:
                last_available = max(
                    last_available, _time(bars[index - lookback]["close_available_at"])
                )
            long = comparison is not None and bid > comparison
            target = Decimal(cast(str, config["quantity"])) if long else Decimal(0)
        expected: JsonRecord = {
            "index": index,
            "decision_at": workflow._stamp(decision),
            "available_at": workflow._stamp(decision),
            "current_bid": str(bid),
            "comparison_bid": str(comparison) if comparison is not None else None,
            "target_quantity": str(target),
            "explanation": "WARMUP"
            if comparison is None
            else "LAGGED_BID_INCREASE"
            if long
            else "FLAT_NONPOSITIVE_MOMENTUM",
        }
        generation = (
            workflow.paper_signal_fields(config, decision)
            if "signal_generation" in config or "signal_generation_contract" in config
            else None
        )
        if generation is not None:
            expected["generation"] = generation
        if (
            type(signal.get("index")) is not int
            or any(signal.get(key) != value for key, value in expected.items())
            or last_available > decision
        ):
            raise SignalError("SIGNAL_FORMULA_OR_AVAILABILITY")
        allowed = set(expected) | {"order_id"}
        order_id = signal.get("order_id")
        at_decision = [
            command
            for command in admissions.values()
            if command.decision_at == decision
        ]
        if snapshot is not None and (
            (order_id is None and at_decision)
            or (order_id is not None and len(at_decision) != 1)
        ):
            raise SignalError("SIGNAL_ORDER_BINDING")
        risk: JsonRecord = {
            "status": "NO_ADMISSION_ATTEMPT",
            "reason": "No recorded order admission for this decision",
            "order_id": None,
            "order_status": None,
        }
        if order_id is not None:
            allowed |= {"admission_status", "admission_reason"}
            if not isinstance(order_id, str):
                raise SignalError("SIGNAL_ORDER_BINDING")
            if snapshot is None:
                risk = {
                    "status": "UNAVAILABLE",
                    "reason": "Latest failure report has no verifiable snapshot",
                    "order_id": order_id,
                    "order_status": None,
                }
            else:
                command = admissions.get(order_id)
                outcomes = _rows(snapshot["outcomes"], p.MAX_COMMANDS)
                matched = [
                    item
                    for item in outcomes
                    if command and item["command_id"] == command.command_id
                ]
                if (
                    command is None
                    or command.decision_at != decision
                    or command.at != decision
                    or command.instrument_id != config["instrument_id"]
                    or command.quote.bid != bid
                    or command.quote.available_at != last_available
                    or len(matched) != 1
                    or signal.get("admission_status") != matched[0]["status"]
                    or signal.get("admission_reason") != matched[0]["reason"]
                ):
                    raise SignalError("SIGNAL_ORDER_BINDING")
                orders = _rows(_record(snapshot["book"])["orders"], p.MAX_COMMANDS)
                order = next(
                    (item for item in orders if item["order_id"] == order_id), None
                )
                risk = {
                    "status": matched[0]["status"],
                    "reason": matched[0]["reason"],
                    "order_id": order_id,
                    "order_status": order["status"] if order else None,
                }
        if set(signal) != allowed:
            raise SignalError("SIGNAL_FIELDS")
        age = now - last_available
        source_status = (
            "NOT_AVAILABLE_AT_QUERY"
            if now < last_available or now < _time(retained["retained_at"])
            else "STALE_AT_QUERY"
            if age.total_seconds() > cast(int, config["max_quote_age_seconds"])
            else "SYNTHETIC_RECEIPTS_WITHIN_FROZEN_QUOTE_AGE"
        )
        withdrawn = (
            head["status"] == "CANCELLED"
            or head["requested"] in {"CANCEL", "KILL"}
            or bool(snapshot and snapshot["killed"])
        )
        uncertain = (
            snapshot is None
            or head["status"] in workflow.BUSY | {"AMBIGUOUS", "FAILED"}
            or verified.get("unreported_native_revisions", 0) != 0
        )
        state = (
            "WITHDRAWN_BY_SESSION_CONTROL"
            if withdrawn
            else "UNVERIFIED_CURRENT_STATE"
            if uncertain
            else "SESSION_ENDED"
            if head["status"] in workflow.TERMINAL
            else "EXPIRED_AT_QUERY"
            if generation is not None and now >= _time(generation["expires_at"])
            else "SUPERSEDED_BY_LATER_DECISION"
            if index + 1 < cast(int, head["cursor"])
            else "RETAINED_NOT_ACTIONABLE"
        )
        result: JsonRecord = {
            "reference": f"{head['id']}:BAR:{index}",
            "bar_index": index,
            **retained,
            "generated_at": _stamp(decision),
            "generated_clock": "SIMULATED_DECISION_CLOCK",
            "decision_at": _stamp(decision),
            "last_required_available_at": _stamp(last_available),
            "direction": "LONG" if long else "FLAT",
            "target_quantity": str(target),
            "explanation": signal["explanation"],
            "source_values": {
                "current_bid": str(bid),
                "comparison_bid": expected["comparison_bid"],
            },
            "horizon": {"status": "UNKNOWN_NOT_FROZEN", "value": None},
            "expiry": {"status": "UNKNOWN_NOT_FROZEN", "at": None},
            "execution_policy": config["execution_policy"],
            "data_status": source_status,
            "quote_max_age_seconds": config["max_quote_age_seconds"],
            "risk": risk,
            "current_status": state,
            "actionable": False,
            "confidence": None,
            "confidence_status": "NO_CALIBRATED_PROBABILITY",
            "evidence_mode": "SYNTHETIC",
        }
        if generation is not None:
            result["generation"] = generation
            result["generated_clock"] = generation["clock"]
            result["horizon"] = {
                "status": "DECLARED_NOT_EVALUATED",
                "value": generation["horizon_bars"],
                "unit": "bars",
                "end_at": generation["horizon_end_at"],
                "within_fixture": generation["horizon_within_fixture"],
                "outcome_available": "NOT_ASSERTED",
            }
            result["expiry"] = {
                "status": "NOT_YET_GENERATED_AT_QUERY"
                if now < decision
                else "EXPIRED_AT_QUERY"
                if now >= _time(generation["expires_at"])
                else "WITHIN_DECLARED_TTL_NONACTIONABLE",
                "at": generation["expires_at"],
                "boundary": generation["expiry_boundary"],
                "comparison_clock": "UTC_QUERY_AGAINST_SIMULATED_TIMESTAMPS",
                "ttl_seconds": generation["ttl_seconds"],
            }
        return result

    def research_jobs(
        self, user: User, *, limit: int = 25, offset: int = 0
    ) -> JsonRecord:
        _page(limit, offset, 9999)
        with self.state.connection() as db:
            db.execute("BEGIN")
            self.paper._actor(db, user, mutation=False)
            budget = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(n),0),COALESCE(MAX(n),0) FROM (SELECT length(CAST(config AS BLOB)) AS n FROM jobs LIMIT ?)",
                (MAX_JOB_SCAN + 1,),
            ).fetchone()
            if (
                budget[0] > MAX_JOB_SCAN
                or budget[1] > MAX_TOTAL_CONFIG_BYTES
                or budget[2] > MAX_JOB_CONFIG_BYTES
            ):
                raise SignalError("SIGNAL_JOB_SCAN_BOUND")
            rows = db.execute(
                "SELECT id,status,experiment_id FROM jobs WHERE owner_id=? AND json_extract(config,'$.kind')='PATTERN_JOB' ORDER BY rowid DESC LIMIT ? OFFSET ?",
                (user.id, limit + 1, offset),
            ).fetchall()
        return _bounded(
            {
                "jobs": [dict(row) for row in rows[:limit]],
                "has_more": len(rows) > limit,
                "limit": limit,
                "offset": offset,
                "classification": "RESEARCH_OBSERVATIONS_NOT_TRADING_SIGNALS",
                "inspection": "OPERATIONAL_METADATA_ONLY",
            }
        )

    def research(self, user: User, identity: str) -> JsonRecord:
        with self.state.connection() as db:
            self.paper._actor(db, user, mutation=False)
        job = self.state.job(user, identity)
        if job.config.get("kind") != "PATTERN_JOB":
            raise AccessError("Research observation unavailable")
        if self.patterns is None:
            raise SignalError("PATTERN_SERVICE_UNAVAILABLE")
        with self.inspection(user):
            try:
                value = self.patterns._job(user, job)
                run = _record(value["run"]) if value.get("run") is not None else None
                result = (
                    _record(run["result"])
                    if run and run.get("result") is not None
                    else None
                )
                return _bounded(
                    {
                        "classification": "RESEARCH_OBSERVATIONS_NOT_TRADING_SIGNALS",
                        "observed_at": _stamp(self._now()),
                        "job": value["job"],
                        "experiment_id": run["experiment_id"] if run else None,
                        "configuration": run["configuration"] if run else None,
                        "bindings": run["bindings"] if run else None,
                        "result_digest": run["result_digest"] if run else None,
                        "model_recipe": value.get("model_recipe"),
                        "model_fit": value.get("model_fit"),
                        "observations": {
                            key: result.get(key)
                            for key in (
                                "method_id",
                                "native_scenario",
                                "method",
                                "state",
                                "configuration",
                                "outcomes",
                                "outcome_histogram",
                                "exposure",
                                "negative_cases",
                                "limitations",
                            )
                        }
                        if result
                        else None,
                        "actionable": False,
                        "confidence": None,
                        "evidence_mode": "SYNTHETIC",
                        "empirical_validation": "MISSING",
                        "limitations": [
                            "Shape similarity and observed conditional returns are not a tradable signal or probability of profit",
                            "Frozen outcome horizon is not a signal expiry; no signal is generated by this read",
                        ],
                    }
                )
            except AccessError, SignalError:
                raise
            except Exception:
                raise SignalError("RESEARCH_OBSERVATION_UNAVAILABLE") from None
