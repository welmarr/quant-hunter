# Bounded instrument metadata, sessions and aggregation

This Phase C component implements cash equity/ETF metadata for XNYS and a named
spot FX convention. It does not certify historical instrument facts, calendar
publication vintages, licensing, executable prices, empirical profitability, or
host enforcement. No broker, live-order, paid-data or network capability exists
in this module. Research gates and the existing experiment lifecycle are unchanged.

## Dependencies and evidence

Pinned runtime dependencies: `exchange-calendars==4.13.2` and
`tzdata==2026.5`. These exact releases are integrated into the canonical manifest
and lockfile and execute in the root Python 3.14.7 environment on D:.
The exchange library supplies XNYS holidays and special closing rules; its
existing XNYS class is bound to the pinned `tzdata` New York resource without
changing process-global timezone state. Both versions are checked when used;
dependency drift fails closed. Package versions and complete session instants
are retained in the calendar snapshot and its canonical SHA-256 identity.

Primary references inspected on 2026-10-05:

- [exchange-calendars release and API documentation](https://pypi.org/project/exchange_calendars/4.13.2/)
- [Maintainer source and session/minute semantics](https://github.com/gerrymanoim/exchange_calendars)
- [Python tzdata release](https://pypi.org/project/tzdata/2026.5/)
- [NYSE official hours and holidays](https://www.nyse.com/trade/hours-calendars)
- [NYSE 2025 calendar](https://www.nyse.com/publicdocs/ICE_NYSE_2025_Yearly_Trading_Calendar.pdf)
- [NIST daylight-saving rules](https://www.nist.gov/pml/time-and-frequency-division/popular-links/time-frequency-z/time-and-frequency-z-d)

NYSE regular cash trading is 09:30–16:00 New York time; the tested 2025-11-28
early close is 13:00 New York time. The module excludes extended sessions. The
hard-coded test oracles convert those wall clocks independently to UTC, before
and after the spring/fall DST changes. A library schedule is a versioned rules
snapshot, not proof that those rules were published at a historical decision
time; unscheduled/security-specific halts and future changes remain unverified.

## Interfaces and identity ownership

Public imports live in `quant_hunter.markets`:

```python
Instrument(...)  # immutable validated metadata
InstrumentRevision(
    instrument,
    recorded_at,
    reason,
    evidence_mode="SYNTHETIC",
    source_reference="SYNTHETIC_TEST_ONLY",
)
InstrumentRevision.from_record(payload)  # strict payload parser
snapshot.to_record()  # JSON-compatible payload, UTC Z
InstrumentHistory(tuple_of_snapshots).as_of(knowledge_time, effective_time)
sessions(calendar_id, start_date, end_date)
aggregate_minutes(
    tuple_of_minute_bars,
    snapshot,
    schedule,
    as_of=utc_instant,
    timeframe="5h",
    partial_policy="DROP",
)
capability("CRYPTO_PERP")  # explicit unimplemented contract
```

The caller must allocate the stable `INSTRUMENT-<uuidv7>` identity before use.
It is never derived from a ticker. Equity/ETF and FX retain asset class, venue,
base/quote currencies, declared decimal precision, lot, tick, multiplier,
timezone, calendar, activity intervals, historical symbols and status. This
initial cash profile requires multiplier one. Decimal values are bounded and
checked on the exact declared tick/lot; no implicit rounding occurs. Three-letter
currency syntax is checked; a three-letter string alone does not verify its ISO
membership or a venue's actual currency support.

The canonical `InstrumentRegistry` allocates identities and recording time on
the server, verifies every retained nested payload, and uses canonical registry
digests for update CAS. It limits each identity to 128 versions and this initial
installation to 1,000 identities. Asset class and base/quote currencies cannot
change within an identity. Reference metadata are explicitly shared across local
authenticated accounts; only owners can create or append revisions. Source
datasets and private credentials keep their separate ownership boundaries.

Activity and symbol intervals are ordered, non-overlapping and half-open. Gaps
are allowed but resolve to UNKNOWN/error, never a guessed ticker. Delisted
metadata can still describe activity before the ending boundary. `recorded_at`
is knowledge time, distinct from interval effective dates. Historical selection
uses the latest snapshot known by the requested knowledge time, then resolves
the effective date within that snapshot. Later corrections therefore cannot
rewrite the earlier view. Source reference and evidence mode are explicit;
`HISTORICAL_DECLARED` is not a verified publication vintage.

The pure immutable `InstrumentHistory` holds at most 128 snapshots and returns
a new object on append. Its stale-caller check uses the latest payload fingerprint.
It is not a second persistent registry or scientific authority. The canonical
`RegistryStore` owns persistent IDs, revisions, locks, CAS and previous-revision
digests through the integration adapter in `markets/registry.py`. The payload
parser accepts only `instrument`, `recorded_at`, `reason`, `evidence_mode`, and
`source_reference`; the adapter verifies and strips the canonical registry
envelope before parsing. Payload fingerprint and registry-file digest are
different domains and must not be substituted for each other.

## Calendar bounds and FX semantics

Calendar requests span at most 366 days within 2000-01-01 through 2035-12-31.
That is an implemented request bound, not a claim that all historical/future
calendar information is independently verified. Sessions are immutable UTC
`[open, close)` intervals, each no longer than 24 hours, without overlap.

`FX_NY_17` requires venue identifier `OTC_NY_17_CONVENTION`: a session labelled
Monday starts Sunday at 17:00 New York and ends Monday at 17:00. Friday closes
at 17:00, then no session exists until Sunday at 17:00. Local DST shifts the UTC
boundary. There is no universal FX exchange calendar. Venue holidays,
maintenance, outages and executable liquidity remain UNKNOWN. This convention
does not assert global FX volume, swaps, forwards or financing treatment.

## Aggregation decisions and limits

Inputs are one-minute OHLC marks for one registered instrument, strictly
chronological, duplicate-free and entirely inside declared sessions/activity/
symbol intervals. Each has explicit `open_at`, `close_at` and `available_at`;
availability cannot precede the complete minute. Optional opening bid and ask
must occur together, be ordered, positive and tick-aligned. OHLC marks are not
silently converted to executable quotes. Unknown volume stays unknown.

Supported granularities are 1m, 5m, 1h and 5h. Every window anchors to its
session opening instant. There is no midnight/UTC-grid fallback and no window
can bridge a session boundary. A normal 390-minute NYSE session yields a
300-minute window plus a 90-minute tail. The required partial policy is either:

- `DROP`: record the short tail as excluded.
- `INCLUDE_CLOSED_SHORT_SESSION_TAIL`: emit the tail only after the actual
  session closes and all constituent minutes are available; flag it explicitly.

Short means a scheduled shorter window, never incomplete live observations.
Any missing minute excludes its entire window; prices and volume are not filled.
Any minute available after `as_of` prevents emission. Equality is eligible.
An intra-window ticker change is explicitly excluded, and a minute crossing a
symbol/activity boundary is rejected. The output retains exact OHLC, source
count, opening quotes, maximum input availability, short-tail flag, exclusions,
as-of, timeframe, partial policy, anchor, metadata fingerprint, calendar digest
and configuration digest. No learned transform, split adjustment or roll occurs.

Work is bounded to 100,000 input minutes and 100,000 expected schedule minutes
per call. Calendar lists, symbol/activity intervals and metadata history are
also bounded. Long datasets must be partitioned on complete session boundaries;
arbitrary row chunks can produce explicit missing-window exclusions and must
not be represented as complete aggregation. Parquet ingestion, persistent
lineage publication and UI integration are owned by the integration layer.

Crypto spot/perpetuals and futures expose capability requirements but remain
unimplemented. Spot/perp separation, venue, 24/7 calendar and fee units are
required; perpetuals additionally require funding/margin/liquidation, and futures
require individual contract/expiry/last-trade/delivery/settlement/roll semantics.
`require_supported` rejects these classes rather than approximating them with
cash-market rules.

## Verification

The focused Windows Python 3.14.3 run passed 90 tests with 98.75% branch-aware
component coverage. Ruff 0.16.6 and strict mypy 1.20.2 passed for the component
and its test file. Initial dependency bootstrap needed an editable installation
for the repository's version lookup; initial test typing failures were corrected.
No full-suite/CI pass or empirical market validation is claimed by this component.
The integration owner runs the complete existing regression and independent review.

```text
python -m ruff check src/quant_hunter/markets tests/test_v0_markets.py
python -m mypy src/quant_hunter/markets tests/test_v0_markets.py --follow-imports=silent
python -m pytest tests/test_v0_markets.py -q --cov=quant_hunter.markets --cov-report=term-missing
```

Tests cover the spring/fall UTC clocks, NYSE holiday and early close, FX weekend,
regular/short sessions, exact 5h + 1.5h arithmetic, missing and late data, unknown
volume, future-price perturbation, immutable historical ticker correction,
invalid quotes/precision/IDs/metadata, parser rejection, resource bounds,
dependency drift and unimplemented crypto/futures contracts. Applicable reviewed
invariants include REG-002–REG-007 and REG-019–REG-020; persistence and lineage
integration must also retain their existing complete checks.
