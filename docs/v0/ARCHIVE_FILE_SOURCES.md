# Bounded archive and forward file imports

This slice supplies actual local readers for SRC-04 CES vintages, SRC-21 standard
FX forward quotes and SRC-22 RTDSM/Philadelphia SPF/ECB SPF exports. It makes no
network calls, uses no credentials, adds no dependency and does not approve data
for point-in-time research. Synthetic fixtures prove software behavior only.

`ProviderService.import_file(catalogue_id, payload, metadata)` reuses the existing
provider-file framework. Root integration must add SRC-04/21/22 to DataAccess's
explicit source-upload allowlist and expose their closed profile fields in the UI;
until that integration is verified this is a provider-service capability, not a
claim that all three are already reachable from the product. The existing
authenticated route, quotas and operation journal remain the host boundary. It
allocates a canonical CANDIDATE SOURCE before parsing submitted data, then
publishes unchanged raw bytes, configuration, lineage, raw-capture manifest and
DATASET through the existing stores. Reimports/corrections create fresh identities
and never replace an earlier value. Failed parsing retains a sanitized failure
and candidate identity; untrusted invalid bytes are not retained. Permission or
closed metadata refusal can occur before allocation. No EXP, model, lifecycle
attempt, source approval or research admission is created.

Each successful response contains the existing diagnostic capture/lineage/raw
digests, record count and at most ten normalized preview rows. The full submitted
file remains immutable and can be parsed again with its frozen profile. This is
not a full normalized research dataset. A configuration digest in scalar raw
request metadata links the complete immutable configuration, including structured
per-vintage units. Origin, transformation, rights and source accuracy remain
owner declarations. Zero local parsing fees do not assert free upstream rights.

## Bounds and common metadata

Only UTF-8 CSV, optionally BOM-prefixed, is accepted. No ZIP/XLSX, compression,
formula execution, auto-detected mappings, URLs or local paths are accepted. The
limit is 2,000,000 bytes, 5,000 data rows, 128 columns, 100,000 total cells,
32,768 characters per physical line and 128 characters per field. Expanded
matrix results also stop at 5,000 observations. Duplicate headers, unequal row
widths, ambiguous times, unsupported decimal precision, nonfinite numbers and
contradictions fail closed. Decimal forward arithmetic uses its own fixed context.

Metadata always requires `profile`, `declared_license`, `license_confirmed=true`,
`start`, `end`, and `export_vintage`. Dates are ISO dates; ranges are inclusive.
`export_vintage` identifies the **owner-declared snapshot/export date**, not a
verified original release date. The server independently stamps receipt time.
No submitted timestamp populates verified `available_at`; all records have
`point_in_time_eligible=false`. Unavailable values remain null, never zero.
Unknown required units or source identifiers are refused.

These are explicit worksheet-export profiles. An owner exports only the stated
table/columns, maps labels as described below, and keeps the original source and
transformation record. The application preserves the exact uploaded CSV, **not**
the original workbook or ZIP. Compatibility with arbitrary native binary files
has not been tested or claimed.

## SRC-04: CES release matrix

Profile `QH_CES_RELEASE_MATRIX_CSV_V1` also requires `series_id`, a CES/CEU
employment-level series ending in `01`. Units are thousands of payroll jobs;
over-month change tables are not this profile. The header is
`vintage_reference_month,2023-12,2024-01,...`; subsequent columns are strictly
increasing economic reference months. Each row begins with the reference month
of the vintage/release being represented, also strictly increasing. This QH
header is an explicit mapped export convention, not an assertion about every
native BLS CSV's headers. A reference-month label must not be relabelled a
publication month. Publication time stays null.

Each cell becomes a separate `(series, reference month, vintage)` observation.
Future triangular empty cells are omitted explicitly; a nonempty observation
after its vintage reference month is refused. Empty/dot/#N/A earlier cells are
retained as missing. We never infer “first release” just because a file's earliest
retained row is the first one encountered. At most 127 reference columns may be
submitted per bounded file; split larger exports explicitly.

Inspected primary documentation: [BLS CES vintage information](https://www.bls.gov/web/empsit/cesvininfo.htm),
modified March6,2026, accessed October5,2026. It describes employment estimates
across successive releases, ongoing revisions, annual benchmarks, seasonal
changes, and published CSV/Excel alternatives. The explanatory text and figure
descriptions were read; no actual archive collection was downloaded. The native
archive schema has therefore not been certified against downloaded data.

## SRC-22: real-time data and surveys

`RTDSM_QUARTERLY_CSV_V1` adds `series_id`, `year_window_start` and `vintage_units`.
The header is `DATE,<series><year>Q<quarter>,...` or monthly `M<month>` vintages.
The observation column accepts `2023:04` or `2023Q4`, both quarter labels. Every
vintage header needs its own explicit unit in `vintage_units`, because historical
base years and definitions may differ. Two-digit years are resolved only within
the frozen 100-year window beginning at `year_window_start`; no system-clock
pivot is used. Four-digit years are also supported. Vintages must be ordered;
quarterly vintage labels mean the middle month. No day/time is inferred.
Blank cells before economic period completion remain absent; a populated such
cell is refused. Different vintages of one quarter remain distinct.

Inspected [RTDSM NIPA general notes](https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/real-time-data/data-files/documentation/gen_doc_NIPA.pdf)
pp1–5, accessed October5,2026: observations are rows, vintages are columns,
quarterly vintages refer to the middle month, and native two-digit year naming
conventions distinguish Q and M vintages. The loader preserves this distinction,
but an uploaded export is not independently authenticated historical receipt.

`PHILADELPHIA_SPF_QUARTERLY_CSV_V1` adds `variable`, `unit`, `statistic` (MEAN or
MEDIAN) and `survey_round=null`. The selected worksheet export must contain
exactly `YEAR,QUARTER,<variable>1,...,<variable>6`. Supported variables/units:

| Variable | Required unit |
|---|---|
| UNEMP | PERCENT_LABOUR_FORCE |
| NGDP | BILLIONS_USD_SAAR |
| RGDP | BILLIONS_REAL_USD_SAAR_BASE_VARIES |
| EMP | THOUSANDS_OF_JOBS |
| INDPROD | INDEX_BASE_VARIES |
| TBILL,TBOND | PERCENT_PER_ANNUM |

Column1 is explicitly `HISTORICAL_VALUE_REPORTED`, for the prior quarter; it is
not a forecast. Columns2–6 target the survey quarter through four quarters ahead.
The original survey date and target period are retained separately. Annual,
growth, probability, individual-response and changing-base transformations are
not silently normalized by this profile. The start/end filter uses survey rounds.

Inspected [Philadelphia SPF documentation](https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/survey-of-professional-forecasters/spf-documentation.pdf),
July28,2026, overview, timing, level-variable format/tables and explicit RGDP1–6
explanation, accessed October5,2026. The native workbooks distinguish median and
mean forecasts; these are not interchangeable with first-release data or a
pre-announcement consensus. Historical units/definitions can change; BASE_VARIES
retains that limit instead of pretending levels are directly comparable.

`ECB_SPF_POINT_CSV_V1` adds `variable`, `unit`, `statistic=INDIVIDUAL_POINT` and
explicit `survey_round` such as `2024Q1`. Export one variable/round's point
columns only: `TARGET_PERIOD,FCT_SOURCE,POINT`. Supported variables HICP/HICPX/RGDP
require PERCENT_YOY; UNEM requires PERCENT_LABOUR_FORCE. Targets are annual years,
quarter labels for RGDP, or English month labels for other variables. Numeric
forecaster IDs remain separate; duplicate forecaster/target entries fail. No
cross-sectional mean/median, probability distribution or event-consensus estimate
is constructed. Targets may be future periods, while survey/export dates may not
be future claims.

Inspected [ECB SPF dataset description](https://www.ecb.europa.eu/stats/prices/indic/forecast/shared/files/SPF_dataset_description.pdf)
sections1–4 and corrections, accessed October5,2026. It documents target-period,
forecaster-ID and point columns, distinct variable tables and horizon units.
Probability and assumptions sections are excluded explicitly. The provider
documents retrospective corrections: a current export is not proof that every
value was available in its original survey round.

## SRC-21: standard forward quotes

`QH_FX_FORWARD_QUOTES_CSV_V1` adds `base_currency`, `quote_currency`, `source_label`.
CSV columns, in order:

```text
quote_id,quote_at,base_currency,quote_currency,spot_date,settlement_date,tenor,quote_kind,spot_bid,spot_ask,forward_bid,forward_ask,point_scale,declared_available_at
```

Rates always mean quote currency per one base currency; there is no automatic
pair inversion. OUTRIGHT takes positive forward bid/ask and requires an empty
scale. POINTS adds its bid/ask to the matching spot bid/ask times an explicit
scale chosen from1 through0.000001 in powers of ten. Example: spot1.10/1.11 and
points−20/−10 at0.0001 produce outright1.098/1.109. This is exact decimal arithmetic.
Both bid/ask pairs must be ordered. Explicit spot and settlement dates are
mandatory, with settlement after spot and at most3660 days away. Supported tenor
labels are positive D/W/M/Y tenors or BROKEN; no holiday/business-day consistency
claim is inferred from the label. The explicit settlement date governs.

Quote IDs must be unique, quote timestamps ordered UTC, and currencies match the
declared pair. Supported codes are USD,EUR,GBP,JPY,CHF,AUD,CAD,NZD,SEK,NOK,DKK,SGD,
HKD,CNH,CNY,MXN,ZAR; other currencies fail explicitly. Optional declared receipt
time must follow quote time and precede server receipt. It remains a declaration.
No forward is represented as FX spot, executable quote, verified dealer feed or
vendor API. LSEG/institutional access and licensing remain BLOCKED_EXTERNAL.
This standard is the project's documented uploader format, not a vendor schema.

## Review and evidence

Tests use synthetic bytes, independent revision/target/Decimal oracles, hostile
CSV bounds, currency/quote/temporal contradictions, missing-value controls and
real canonical registry/object publication. Earlier test evidence retained:
first run89PASS with3 setup/teardown test-ID size failures plus1 nested raw-request
schema failure; shortened explicit test IDs and an exact immutable configuration
reference corrected them. The second run93PASS with94.05% combined branch/statement
coverage preceded the final target-granularity/currency hardening. Final exact-byte
results and independent review are recorded in the handoff manifest; they are
software evidence only. Root full regression, integration/UI and hosted checks
remain separate gates.
