"""Reusable spot execution contract and an actual, exclusively offline test plugin."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never, Protocol, runtime_checkable

from quant_hunter.simulation import accounting as a
from quant_hunter.simulation import paper_engine as p


class CryptoExecutionError(ValueError):
    """Closed plugin errors; no credentials, endpoints or transport exist here."""


@dataclass(frozen=True)
class CryptoCapabilities:
    venue: str = "OFFLINE_CRYPTO_FIXTURE"
    evidence_mode: str = "SYNTHETIC"
    market: str = "CRYPTO_SPOT"
    order_types: tuple[str, ...] = ("MARKET",)
    partial_fills: bool = True
    cancellation: bool = True
    replacement: bool = False
    shorting: bool = False
    leverage: bool = False
    network: bool = False
    scientific_authority: bool = False
    actual_broker_access: str = "NOT_IMPLEMENTED"


@runtime_checkable
class CryptoExecutionAdapter(Protocol):
    """Host-authenticated contract; every mutation requires native journal CAS.

    Admit carries strategy, decision/quote times, quantity and a commission
    reservation. The concrete plugin must apply actual atomic risk admission;
    there is no caller-provided boolean which can approve a rejected order.
    """

    def capabilities(self) -> CryptoCapabilities: ...
    def account(self) -> p.PaperSnapshot: ...
    def positions(self) -> tuple[a.Position, ...]: ...
    def get_order(self, order_id: str) -> a.Order: ...
    def submit(
        self, intent: p.Admit, *, expected_revision: int, order_type: str = "MARKET"
    ) -> p.PaperSnapshot: ...
    def synthetic_execution(
        self, event: p.Match, *, expected_revision: int
    ) -> p.PaperSnapshot: ...
    def cancel(
        self, request: p.Cancel, *, expected_revision: int
    ) -> p.PaperSnapshot: ...
    def reconcile(
        self, observation: p.Reconcile, *, expected_revision: int
    ) -> p.PaperSnapshot: ...
    def events(
        self, *, after_revision: int = 0, limit: int = 100
    ) -> tuple[p.Outcome, ...]: ...
    def executions(
        self, *, after_fill: int = 0, limit: int = 100
    ) -> tuple[a.Fill, ...]: ...


class OfflineCryptoPlugin:
    """Uses a real persistent PaperEngine account, with no separate economic ledger.

    The trusted host binds this instance to the current owner. It supplies an
    already registered account, immutable configuration/provenance and strategy
    references; this plugin cannot allocate or approve research objects. All
    account reads and writes verify the bound owner in the native journal.

    after_commit is a test-only process-fault hook, never request configuration.
    If the caller loses an acknowledgement, query the journal before any action.
    The plugin does not retry or resubmit on its own.
    """

    def __init__(
        self,
        engine: p.PaperEngine,
        account_id: str,
        owner_id: str,
        *,
        after_commit: Callable[[], None] = lambda: None,
    ) -> None:
        self._engine, self._account_id, self._owner_id = engine, account_id, owner_id
        self._after_commit = after_commit
        self.account()

    def capabilities(self) -> CryptoCapabilities:
        return CryptoCapabilities()

    def account(self) -> p.PaperSnapshot:
        state = self._engine.load(self._account_id, self._owner_id)
        if (
            state.provenance.evidence_mode != "SYNTHETIC"
            or state.provenance.mode not in {"REPLAY", "LOCAL_PAPER"}
            or not state.book.instruments
            or any(
                instrument.kind != "CRYPTO_SPOT"
                for instrument in state.book.instruments
            )
        ):
            raise CryptoExecutionError("SYNTHETIC_SPOT_ACCOUNT_REQUIRED")
        return state

    def positions(self) -> tuple[a.Position, ...]:
        return self.account().book.positions

    def get_order(self, order_id: str) -> a.Order:
        for order in self.account().book.orders:
            if order.order_id == order_id:
                return order
        raise CryptoExecutionError("ORDER_NOT_FOUND")

    def _process(
        self, command: p.PaperCommand, expected_revision: int
    ) -> p.PaperSnapshot:
        self.account()  # Bound owner/mode; native process repeats ownership atomically.
        result = self._engine.process(
            self._account_id, self._owner_id, command, expected_revision
        )
        self._after_commit()
        return result

    def submit(
        self, intent: p.Admit, *, expected_revision: int, order_type: str = "MARKET"
    ) -> p.PaperSnapshot:
        if type(intent) is not p.Admit or order_type != "MARKET":
            raise CryptoExecutionError("UNSUPPORTED_ORDER_TYPE")
        return self._process(intent, expected_revision)

    def synthetic_execution(
        self, event: p.Match, *, expected_revision: int
    ) -> p.PaperSnapshot:
        if type(event) is not p.Match:
            raise CryptoExecutionError("MATCH_EVENT_REQUIRED")
        return self._process(event, expected_revision)

    def cancel(self, request: p.Cancel, *, expected_revision: int) -> p.PaperSnapshot:
        if type(request) is not p.Cancel:
            raise CryptoExecutionError("CANCEL_EVENT_REQUIRED")
        return self._process(request, expected_revision)

    def reconcile(
        self, observation: p.Reconcile, *, expected_revision: int
    ) -> p.PaperSnapshot:
        if type(observation) is not p.Reconcile:
            raise CryptoExecutionError("RECONCILIATION_EVENT_REQUIRED")
        return self._process(observation, expected_revision)

    def set_kill(self, request: p.Kill, *, expected_revision: int) -> p.PaperSnapshot:
        if type(request) is not p.Kill:
            raise CryptoExecutionError("KILL_EVENT_REQUIRED")
        return self._process(request, expected_revision)

    def set_health(
        self, request: p.Health, *, expected_revision: int
    ) -> p.PaperSnapshot:
        if type(request) is not p.Health:
            raise CryptoExecutionError("HEALTH_EVENT_REQUIRED")
        return self._process(request, expected_revision)

    def mark(self, quote: p.Mark, *, expected_revision: int) -> p.PaperSnapshot:
        if type(quote) is not p.Mark:
            raise CryptoExecutionError("MARK_EVENT_REQUIRED")
        return self._process(quote, expected_revision)

    @staticmethod
    def _page(after: int, limit: int) -> None:
        if (
            type(after) is not int
            or not 0 <= after <= 1000
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise CryptoExecutionError("EVENT_PAGE_BOUND")

    def events(
        self, *, after_revision: int = 0, limit: int = 100
    ) -> tuple[p.Outcome, ...]:
        self._page(after_revision, limit)
        return self.account().outcomes[after_revision : after_revision + limit]

    def executions(
        self, *, after_fill: int = 0, limit: int = 100
    ) -> tuple[a.Fill, ...]:
        self._page(after_fill, limit)
        return self.account().book.fills[after_fill : after_fill + limit]

    def replace(self) -> Never:
        raise CryptoExecutionError("REPLACEMENT_NOT_SUPPORTED")
