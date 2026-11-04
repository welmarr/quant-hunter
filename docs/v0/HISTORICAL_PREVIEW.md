# Historical chart-only inspection

`HistoricalPreviewAccess(state, quality)` exposes bounded literal charts over an
account's own verified quality datasets. It uses the existing
`EXPLORATORY_INSPECTION` purpose and does not change any quality or research
admission rule. No neighbor search, motif discovery, fit, prediction, outcome
calculation, backtest, sealed-data release or research identity is created.

This profile requires `evidence_mode=HISTORICAL`,
`admission=HISTORICAL_EXPLORATORY`, and `causal_eligible=false`. Historical data
with missing availability, REQUIRED_UNKNOWN revision timing, invalid instrument
or calendar support, or missing expected trading minutes retains the existing
BLOCKED decision, including for charts. Declared known timestamps still do not
establish independently verified historical knowledge. The application must
display the exact refusal and the missing data; it must not silently read the
normalized object around the selector. Synthetic software charts use the
existing separately labeled workflow.

## Host integration and UI contract

Construct the adapter with the existing AppState and QualityAccess, then call
`install_historical_routes(app, authenticated, access)`. The host retains its
ordinary64KiB request limit, current authentication, origin and CSRF checks.
All responses containing inspection evidence carry `Cache-Control: no-store`.
There is no client-supplied path, URL, SQL, Python method or artifact digest to
open directly. The record and report digests below are exact selection receipts,
not arbitrary object-read authority.

`POST /api/quality/inspections` takes the closed JSON object:

```json
{
  "dataset_id": "existing owned canonical DATASET identifier",
  "record_digest": "exact canonical dataset revision digest",
  "quality_report_digest": "exact quality report digest",
  "start": 0,
  "stop": 100
}
```

Bounds are zero-based and half-open, nonnegative integers, at most100,000 and
within the actual dataset. At most512 rows may be selected. POST explicitly
records an inspection audit, so CSRF is required even though readers can inspect
their previously owned data. Cross-account selections are denied before any
source graph or Parquet replay.

The201 response contains:

- `inspection_id`, `inspection_receipt_digest`: operational audit references,
  not PATTERN/MOD/EXP identities.
- `snapshot`: exact dataset revision, normalized object, quality report,
  instrument revision, calendar, step, feature order, bounds, admission and
  reasons from the existing selected-snapshot contract.
- `source`: exact source ID, raw dataset ID, raw digest, configuration digest and
  original uploader metadata/rights declarations. These remain declarations.
- `mapping`: the retained mapping configuration.
- `row_start`, `row_stop`, `feature_columns`, and `rows`.
- `availability_mode=UPLOADER_DECLARED_UNVERIFIED`,
  `causal_research=BLOCKED`, false empirical/host-validation flags and explicit
  limitations.

Each row has `row` (normalized index), `source_row` (original row identity),
`open_ns`, `close_ns`, `available_ns`, `revision_ns`, `ingestion_ns`,
`revision_time_status`, `gap_before_ns` and `values`. Timestamps and gap widths
are decimal nanosecond strings. Values are lossless decimal strings in the
declared feature order, close first. There are no normalized curves or computed
outcomes. The first selected row's preceding gap is unknown/null because the
adapter does not read a row outside the requested range. Later session gaps are
explicit; no interpolation creates an apparent observation. The codec preserves
nullable declared times, although the current public quality selector rejects
missing timing before chart delivery.

For display, preserve the source feature labels, timestamp distinctions,
exploratory banner and gap markers. Never connect an overnight gap as though it
were a continuous minute observation or turn a missing value into ingestion
time. Numeric conversion for plotting must not replace the lossless table and
receipt. Rights/source strings are untrusted text, never executable markup.

`GET /api/quality/inspections?limit=25&offset=0` returns an owned audit page under
`inspections` (maximum50, offset below10,000). `GET
/api/quality/inspections/{inspection_id}` returns request/status and verified
immutable audit metadata. Neither endpoint replays source rows or grants fresh
source admission. A new chart view makes another explicit inspection request.

## Resource and audit boundaries

One existing transient inspection slot is acquired before heavy graph replay.
The existing data capacity check runs before audit publication. Ownership,
exact record/report bindings and the complete governed quality graph are then
verified. The Parquet reader has no filesystem or network input, processes
bounded4096-row batches, and returns only the requested range. Response bytes
are capped at1MB and normalized input bytes at64MB, in addition to the existing
stricter source-ingestion bounds.

A global maximum of10,000 operational inspection rows bounds this initial audit
journal. STARTED is recorded before source inspection. The immutable success
receipt binds the exact request, selected snapshot, owner, observation time and
SHA256 of the returned response before its receipt-digest field is appended.
It does not duplicate the actual bars. Its disposition is
`SERVER_PREPARED_FOR_DELIVERY; NOT_CLIENT_ACKNOWLEDGEMENT`; a successful server
response cannot prove the user saw it. Terminal PREPARED/FAILED states and audit
identities cannot be overwritten or deleted through the SQLite interface.

Failures retain sanitized reasons. Process interruption leaves STARTED visible;
construction and audit reads never retry or replay it. Immutable publication
followed by a failed operational finalization can leave an unlinked receipt,
which grants no ownership. No second experiment lifecycle or scientific ledger
is introduced. Research datasets and registry revisions remain unchanged by
inspection. No historical causal research gate is closed by this capability.

## Executed evidence

The first24 tests passed in34.85seconds. The final44 tests passed with warnings
treated as errors and94.94% combined statement/branch coverage. Ruff and strict
mypy on both modules passed. They use real SQLite, governed registries, quality
mapping and immutable Parquet, with generated numbers declared historical only
to exercise this software profile; they contain no real market evidence.

The tests independently check exact Decimal prices/nanosecond timestamps, a real
XNYS overnight boundary, an exact512-row view, original bytes unchanged, no new
research identities/jobs, foreign denial before replay, owned-reader access,
unchanged causal and BLOCKED-quality rejection, shared admission, quota and
failure retention, current actor checks, immutable audit triggers, rehashed
foreign receipt fields, restart-without-replay and sanitized closed HTTP routes.
Pure codec hostile tests are separate from public quality admission and cannot
make an inconsistent object eligible.

The final XML is `D:/quant-hunter/.tools/ui-historical-final.xml`, coverage is
`D:/quant-hunter/.tools/ui-historical.coverage`, and the exact reference package
is `D:/quant-hunter/.tools/operations-reference`. The measured final wall time
was1029.29seconds, including955.36seconds attributed to one audit-trigger test
and an overlapping951-second tool-poll stall; this unusually long measurement
is retained, not silently replaced by the earlier run. The unchanged trigger test
then passed separately in12.52seconds (10.53seconds setup,0.83seconds test call),
43deselected. This does not reproduce persistent blocking in that path or erase
the longer observation. Independent review is recorded separately in the handoff.
Full integration regression, browser and remote CI remain parent-owned gates.
