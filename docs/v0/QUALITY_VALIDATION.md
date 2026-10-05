# Data quality and chronological execution

This additive backend supplies immutable mapped imports, quality diagnostics,
causal aggregation, bounded partition selection and execution under existing
Item 9 temporal plans. Item 8 remains the only experiment/attempt authority.
Nothing here grants scientific approval, deployment authority or sealed access.

## Data contract

`QualityService(registry, objects, schema_root, code_revision, environment_digest)`
uses the existing governed stores. Environment evidence includes verification of
an optional retained source-code archive. The application must establish owner
access before passing dataset IDs to any operation; this service intentionally
has no global list or ownership-bypass endpoint.

`ingest_mapped` accepts actual CSV/Parquet bytes, explicit `MappingSpec`, existing
canonical INSTRUMENT ID and revision digest, calendar dates, and bounded source,
license and evidence-mode declarations. Input is limited to 2 MB, 100,000 rows and
16 MB decoded data. Parquet page/header allocation preflight reuses the existing
physical-page validator. External column chunks, nested/variable-width data,
custom metadata and excessive expansion are rejected.

The profile requires one-minute `open_at`, `close_at`, `open`, `high`, `low`,
`close`; availability, revision time, volume and paired opening bid/ask are
explicit optional mappings. Unknown availability remains null. Source timezone
is explicit (`OFFSET_REQUIRED`, UTC or pinned America/New_York rules); ambiguous
and nonexistent local timestamps fail. Quote-unit scales are explicit 1, 0.01 or
0.0001. Currency must match the canonical instrument quote currency. Volume is
explicit units or lot-size multiples. No fitted cleaning, sorting, zero filling,
imputation or inferred opening midpoint is performed.

`REJECT_DATASET` is the default. `EXCLUDE_WITH_REPORT` requires an explicit caller
choice and retains every source row number and exclusion reason. Accepted raw
bytes stay exact, including explicitly excluded observations. Failed input audit
retains only a digest, size, stable reason and bounded dispositions; malformed
raw bytes need not be published. SOURCE is CANDIDATE before publication; original
raw DATASET and derived normalized DATASET get permanent canonical IDs. The raw
logical interpretation is explicitly an injective hex-byte envelope, separate
from both its physical hash and mapped market semantics. Every successful mapped
version retains raw, initial configuration, capture, source, mapping, instrument,
calendar, quality and derived three-identity lineage. Reimports create new IDs.

Quality checks include unique ordered minutes, OHLC/quotes, Decimal/tick and
volume grids, declared availability/revisions, activity/symbol boundaries,
sessions and internal trading-minute gaps. Calendar checks cover the observed
start/end range; they cannot certify omitted pre/post-history. Corporate-action
completeness, suspensions not represented in metadata, survivorship, price
accuracy, source rights and historical metadata-publication times remain
explicitly unverified. A clean structural report never changes a canonical
SOURCE or DATASET status to APPROVED.

Admission is `SYNTHETIC_SOFTWARE_ONLY`, `HISTORICAL_EXPLORATORY` or `BLOCKED`.
Only the first has `causal_eligible=true`. Required-unknown revisions, unknown
availability, gaps or invalid instrument/calendar/grid checks block selection.
Even uploader-declared known historical revisions remain exploratory and cannot
enter causal Pattern search in this profile. Raw provider diagnostics and older
unreviewed imports are not silently upgraded into this transformation.

`get_dataset` replays the whole graph. `select(id, expected_record_digest,
expected_report_digest, purpose)` returns a `SelectedSnapshot` and verified
Parquet bytes, subject to admission. Purpose is closed to causal Pattern/research
or exploratory inspection. The snapshot binds actual DATASET, record, normalized,
quality, INSTRUMENT revision, calendar, bounds, row count, cadence and features.

`aggregate` calls the existing minute/session engine and publishes a new curated
DATASET. Complete 1m/5m/1h/5h windows use session-open anchoring, explicit short-tail
policy and maximum constituent availability. Excluded/future/incomplete windows
remain in immutable evidence. Valuation marks and optional opening quotes retain
their different meanings. No history is overwritten.

## Partitioned corpus intake

`compose(tuple[(dataset_id, record_digest, quality_report_digest), ...], purpose)`
accepts at most 1,024 caller-owned immutable parents and 50 million aggregate
rows. Individual parser limits are unchanged. Instrument revision, cadence,
features, mode and admission must match. Calendar schedules may differ by date;
their calendar ID, rule package/version, timezone package/version and anchor must
match. Parents must be chronological and disjoint; boundary gaps remain explicit
with no imputation or continuity claim.

`PartitionSelection` binds all parent snapshots and a collective immutable
manifest digest, without inventing a collective normalized DATASET ID.
`iter_batches(manifest_digest)` verifies the manifest then yields
`(parent_index, RecordBatch)` with at most 4,096 rows per batch, rechecking each
parent before use. The caller must check owner access to every parent on every
new operation. Item 8 freezes all parent DATASET IDs and the selection digest.
Pattern corpus construction may allocate its own real DATASET and retain all
parents. Consumers must check actual window cadence and session gaps; a manifest
does not make noncontiguous data contiguous.

## Chronological execution

`protocol_document` constructs a preregisterable immutable application protocol
containing the actual existing Item 9 `ValidationPlan`, fixed bootstrap controls,
sample thresholds and multiple-testing policy. Store that document under
`chronological_validation` in the configuration before Item 8 registration.
Optional statistical-test definition digests refer to actual retained artifacts.

`ResearchValidationService.bind` resolves the canonical Item 8 history and exact
FROZEN revision, checks the frozen application protocol and invokes Item 9's
`bind_frozen_temporal_validation`. `bind_scientific_plan` accepts an actual Item9B
plan only when identities and every scientific declaration match the frozen
`scientific_requirements` configuration. It does not mark any gate passed.

Observation metadata include decision time, feature interval and receipt time,
label interval and label receipt time. `resolve_membership` implements actual
row inclusion/exclusion, rather than assuming intervals alone prove membership.
Feature receipt must precede the decision; fitting labels must be received by
the fold training cutoff. Dependency overlap with exact purge/embargo intervals
is excluded and retained. Validation labels crossing their evaluation interval
are excluded. Sealed-period observations are refused. Exact Item9 fractional
boundaries are compared without float or datetime truncation.

`execute` requires actual RUNNING Item8 state, binds the frozen controls and fits
the trusted callback independently for each fold. The callback receives eligible
training features/labels, then one validation feature vector at a time; no
validation label is passed for fitting. Delayed validation labels stay pending
without reading their numeric values. Insufficient or not-yet-closed folds do not
fit. Callback failures propagate so the application finalizes the Item8 failure;
there is no hidden retry or competing attempt counter. Callbacks are trusted
internal code, not a sandbox against arbitrary Python/closure access.
The application must resolve feature values and observation metadata from the
exact owner-authorized DATASET objects frozen in the experiment. The callback
adapter binds the protocol and lifecycle; it does not authenticate arbitrary
caller-created numeric rows against source bytes.

The existing Item9 scheme keeps all training folds inside development and all
evaluation folds inside validation; this does not silently implement retraining
on prior validation outcomes. Embargo remains fold-local. The host OOS gate is
still blocked; sealed references remain metadata only.

## Uncertainty and selection

See the proposed decision in `QUALITY_VALIDATION_DECISION.md`. The bounded
noncircular moving-block mean bootstrap uses a fixed preregistered block length,
seed, repetition count, confidence and minimum sample. It reports a mean interval,
not a fabricated selected-strategy probability or p-value. Every change is a new
counted variant. Holm step-down uses exact bounded Decimal arithmetic and does
not depend on ambient Decimal precision.

The family inventory reads actual canonical EXP heads, including failed,
unfinished and rejected trials. Adjustment uses retained per-attempt result
artifacts bound to actual attempt configuration and preregistered test definition.
Missing/failed/unfinalized trials remain in exposure and force INCONCLUSIVE with
no adjusted p-values. The service rechecks the inventory before returning an
assessment. A complete arithmetic correction still reports empirical INCONCLUSIVE
and never grants promotion. Test calibration, dependence assumptions and all V0–V9
gates remain separate requirements.

All tests are synthetic software/math evidence. Full regression, independent
review, UI wiring and hosted CI remain root integration responsibilities.

## Private quality application adapter

`web.quality_access.QualityAccess(state, service, data, instruments)` adds private
dataset and selection pointers to the existing operational SQLite store. It uses
`DataAccess._begin` and its shared data/publication two-operation limit, cumulative
operation quota and disk policy. It adds no registry identity or research state.
Composition and aggregation enter that shared admission before decoding/replaying
parent graphs. Known importer registry/object stores must be the same instances.
The host supplies the same governed stores and verifies the authenticated user.
Owner/researcher users can write their own data; readers can read their own data.
Ownership checks precede each parent read/use. Canonical record and quality-report
digests are exact required receipts, with stale requests rejected as HTTP 409.

Success and all returned ownership pointers commit in one SQLite transaction.
Interrupted operations retain evidence and never replay automatically. Immutable
objects published before a crash can remain unlinked; they cannot be claimed by
submitting an arbitrary dataset ID. Existing `DataAccess.recover()` marks their
RUNNING operations INTERRUPTED. Service failures retain sanitized codes and an
audit digest where the immutable validator produced one. No raw rejected content
or arbitrary exception text appears in operational errors.

`install_quality_routes(app, authenticated, quality)` installs:

- GET `/api/quality/datasets`: private hash-verified metadata summaries, explicitly
  `IMMUTABLE_METADATA_SUMMARY; NOT_FRESH_ADMISSION`; list entries set
  `causal_eligible=false` and retain the prior report's `reported_admission`.
  The list never decodes raw/Parquet rows or grants present admission. GET
  `/{dataset_id}` performs the complete fresh graph replay under a read reservation.
  The paginated list has `{datasets: [...]}`, limit 1–50, offset 0–1000, and a 2 MB
  summary budget; an over-budget page fails explicitly with
  `QUALITY_SUMMARY_PAGE_LIMIT_REDUCE_LIMIT`. It never silently skips entries.
- POST `/api/quality/datasets`: explicit `content_base64`, CSV/PARQUET format,
  source/license/evidence/instrument metadata, full `MappingSpec` record, existing
  `instrument_id`, exact `instrument_revision_digest`, and inclusive calendar
  start/end dates. Raw input remains at most 2 MB and 100,000 rows.
- POST `/api/quality/datasets/{dataset_id}/aggregate`: exact `record_digest` and
  `quality_report_digest`, timeframe 1m/5m/1h/5h, `partial_policy` DROP or
  INCLUDE_CLOSED_SHORT_SESSION_TAIL, and an explicit aware `as_of` instant.
- GET/POST `/api/quality/selections` and GET `/{manifest_digest}`: private
  composition. POST accepts 1–1024 `{dataset_id, record_digest,
  quality_report_digest}` receipts in chronological order, plus purpose
  PATTERN_CAUSAL, RESEARCH_CAUSAL or EXPLORATORY_INSPECTION. Responses are the exact
  `PartitionSelection.to_record()` shape, retaining each parent snapshot and
  report. Detail reads reverify every owned parent and replay the immutable manifest.
  List reads hash-check bounded manifest metadata and ownership, retain the
  declared parent snapshots, mark `causal_eligible=false` and
  `IMMUTABLE_METADATA_SUMMARY; NOT_FRESH_ADMISSION`, and use the same fail-closed
  2 MB page budget. Reduce `limit` when requested; a single oversized summary fails.
- GET `/api/quality/operations`: current user's quality operations in the existing
  latest-100 resource journal, with sanitized failure or interruption evidence.
- POST `/api/quality/demo` with `{}`: explicit owner-only generation of two new
  synthetic XNYS instruments and 240 one-minute OHLC/bid/ask bars per instrument
  on 2025-01-06. The returned `datasets` are genuine newly governed records,
  `evidence_mode` is SYNTHETIC and generator version is `qh-quality-demo-v1`.
  Nothing runs at startup or calls a market provider.

The host must grant a 3 MB body bound only to the mapped-upload POST and 1 MB only
to the composition POST; ordinary requests keep the host's 64 KiB bound. Models
reject extra fields, paths and unsupported types. Invalid field responses omit
input values. Multiple files are uploaded sequentially under the unchanged
per-file limits, then explicitly composed. These routes perform no research
evaluation and allocate no EXP; the consuming Pattern/research host must create
and start its actual Item8 attempt before evaluation.

Dataset detail contains the exact `SelectedSnapshot` fields plus source/raw IDs,
raw/configuration digests, metadata and the complete `quality` report. It always
reports `empirically_validated=false` and `host_enforced=false`. REQUIRED_UNKNOWN
timing remains BLOCKED even for exploratory selection; private detail/reject-report
inspection remains available. A HISTORICAL_EXPLORATORY record with sufficient
declared timing still cannot enter causal search or become empirical proof.

Trusted server consumers use `selected(user, dataset_id, record_digest=...,
quality_report_digest=..., purpose=..., operation_id=...)` for one verified snapshot/byte object,
or `iter_selection(user, manifest_digest, operation_id=...)` for `(parent_index, RecordBatch)`
streams. Selection ownership and all exact parent receipts are checked before
iteration; each yielded parent's ownership is rechecked. Client-supplied paths,
global registry discovery and undeclared source imports are unavailable.

Detailed public `dataset`, `selection`, `selected` and `iter_selection` reads use
`quality.inspection(user, operation_id=None)`: an authenticated reader may hold
one transient `resource_readers` SQLite reservation, counted by the shared two
active/eight total resource limit. Its `finally` deletes the reservation even
on a normal exception or generator close; leased startup recovery clears remnants
after process loss. Reads do not consume the 1000 import-operation quota or create
scientific attempts. Passing an internal `operation_id` bypasses a second slot
only after verifying the actual owned RUNNING data operation. Clients cannot pass
that argument through routes. Private `_dataset`, `_selected`, `_receipt` and
`_selection` are for trusted callers already inside an admitted resource scope.
No summary replaces the full admission check before research or corpus consumption.
