# Macro sources — bounded Phase B slice

The standalone modules implement two HTTP clients and two explicit file importers.
They do not approve sources, allocate research objects, evaluate strategies or
assert point-in-time eligibility. Root integration owns secure configuration,
candidate registration, immutable governed capture, quotas and catalogue/UI status.
The mission catalogue keys below are not canonical source registry identifiers.

| Catalogue | Implemented scope | External readiness |
| --- | --- | --- |
| SRC-05 BEA | Sanitized NIPA JSON response importer | API transport `BLOCKED_EXTERNAL`: verified API contract puts UserID in the URL |
| SRC-06 Federal Reserve G17 | One dated ASCII release; six monthly total industrial-production index levels | Credential-free bounded archive client; archive layout must match its strict contract |
| SRC-07 FRED | v2 release-observations client with Bearer header authentication and bounded pagination | `NOT_CONFIGURED`; authenticated live verification `BLOCKED_EXTERNAL` without an owner key |
| SRC-07 ALFRED | v1 observations JSON plus separate series metadata importer; every supplied revision retained | API transport `BLOCKED_EXTERNAL`: verified v1 contract puts api_key in the URL |

No key, account or paid service was acquired. Source documentation and access
terms were reviewed on 2026-10-05. A client's successful parse is software evidence,
not evidence of scientific fitness, licensing approval or complete coverage.

## Shared records and bounds

`MacroObservation` keeps the catalogue key, series ID, economic period, period
start, exact Decimal value or missing value, unit, unit multiplier, ingestion
time and vintage. Where supported, it also keeps the stated publication timestamp,
closed real-time date interval, series update timestamp and metric. All records
have `available_at=None`, `revision_time=None` and `point_in_time_eligible=False`.
They never substitute a retrieval or economic date for historical availability.

`MacroBatch` contains observations, exact submitted response pages with SHA-256
digests, evidence mode and explicit limitations. Coverage is always incomplete.
Injected transports produce `RECORDED_FIXTURE`; genuine default transports use
`HISTORICAL_REAL`. File imports use `OWNER_SUPPLIED` or `RECORDED_FIXTURE`, never
authenticated-acquisition evidence. The caller must retain the bytes, source
revision, configuration and environment through the governed capture service.

Each response is bounded to 2 MiB. JSON parsing rejects duplicate keys. Values
must use bounded plain decimal syntax: at most 38 digits, exponent -12 through
24, absolute value at most 10^24. Missing observations remain missing. Units,
series identities, revision intervals, ordering and duplicate observations are
validated. No silent numerical rescaling occurs: BEA's base-ten `unit_multiplier`
is preserved separately and must match the requested unit context.

`MacroHTTPS` permits only the two exact official hosts and path/query contracts.
It pins a validated public DNS address into a TLS connection while validating
the official hostname. It refuses redirects, private addresses, proxy discovery,
compressed responses and arbitrary URLs; it performs no retries. Each request
runs in a resource-bounded child with a twenty-second parent wall deadline
covering startup, DNS, connection, TLS, headers and body, followed by bounded
termination/reaping. Socket/body timeouts are additional limits. See
SOURCE_HTTP_BOUNDARY.md for the exact process contract. FRED bearer values
are hidden from repr, sent only in a header, and checked against raw, JSON-escaped
and URL-escaped response text before any response page may be retained. Transport
exceptions expose sanitized codes. No environment variable is loaded implicitly.

## G17 archive, SRC-06

`G17Connector(transport=None)` exposes `validate_config`, `test_connection`,
`list_capabilities`, `fetch_range`, `normalize`, `validate_batch` and `health`.
`G17Query(release_date, expected_base_year=2017)` selects exactly one
`https://www.federalreserve.gov/releases/g17/YYYYMMDD/g17.txt` release. It does not
fetch the revised current series or traverse all archives. `last_raw` retains a
bounded response when parsing fails, so the caller can preserve failure evidence.

The parser deliberately supports only the summary's six seasonally adjusted
total-IP index levels. It verifies the release header/date, index base, month
sequence, year rollover, positive values and revised/preliminary qualifiers.
Other tables and the previous-estimates row remain in raw bytes and are not
silently merged. Unsupported historical layouts fail with a sanitized error.

An explicit EST/EDT release time is converted to UTC and preserved as stated
publication time. Ambiguous ET produces an unknown publication timestamp.
The release date identifies the release version; economic dates identify the
observed months. Neither proves when a downstream system could actually obtain
the information. Current downloads from a dated archive do not authenticate
historical delivery or guarantee that the archived file was never corrected.

The Board links dated ASCII releases and provides its release calendar.
[G17 archive](https://www.federalreserve.gov/releases/g17/),
[release calendar](https://www.federalreserve.gov/releases/g17/release_dates.htm),
[January 17, 2024 release](https://www.federalreserve.gov/releases/g17/20240117/g17.txt).
The Board describes its own public information as public domain with attribution
requested; third-party material has separate rights. The local diagnostic scope
is a small Board-produced release, not blanket reuse permission for other sources.
[Board disclaimer and reuse guidance](https://www.federalreserve.gov/disclaimer.htm).

## FRED v2 and ALFRED v1, SRC-07

`FREDReleaseConnector(key=None, transport=None)` exposes the same seven methods.
`FREDKey(value)` stores an explicitly configured key hidden from repr.
`FREDReleaseQuery(release_id, page_size=1000, max_pages=5)` requests current
observations for one release. The interface name `fetch_range` means this bounded
page range; the official v2 endpoint has no implemented economic-date or
series-selector filter. This is not a complete-release or all-history claim.

The fixed v2 endpoint supports `Authorization: Bearer` in the official contract.
The client requests JSON, follows at most five cursors, and limits each page to
1,000 observations. It rejects repeated cursors, contradictory pagination state,
duplicate or unordered observations and changes to the same series' units,
source-update time, frequency, seasonality or rights across pages. Separate series
may still update while pages are being acquired; no atomic snapshot is asserted.
Source `last_updated` remains a series-update timestamp, not observation
publication or vintage. Rights qualifiers remain visible on observations.
[FRED v2 authentication](https://fred.stlouisfed.org/docs/api/fred/v2/api_key.html),
[release-observations contract](https://fred.stlouisfed.org/docs/api/fred/v2/release_observations.html).

`ALFREDFileImporter.import_bytes(raw, series_metadata, query, retrieved,
evidence_mode="OWNER_SUPPLIED")` accepts `ALFREDImportQuery(series_id, unit,
realtime_start, realtime_end, observation_start, observation_end)`. Both files
together are limited to 2 MiB. The importer supports complete, offset-zero,
linear-unit, output-type-1 JSON exports ordered by economic date and real-time
start. It refuses partial counts, overlapping closed vintage intervals and
contradictory query metadata. Old and revised values remain separate records.
An actual economic date or revision interval start after retrieval is rejected.
Future query bounds and open validity ends such as `9999-12-31` remain permitted;
an interval end is not a claim that a future revision has already occurred.

The observations response itself lacks a series ID and native unit; separate
official-shaped `seriess` metadata must contain exactly the requested ID/unit.
This is an owner-supplied binding, not authenticated linkage. Real-time dates
have date-level closed interval meaning. Intraday historical availability is
unknown, so even an otherwise valid vintage import is not marked PIT eligible.
No alternative header/body authentication was verified for the v1 API; the
importer has no pretend network method and never emits a query-key request.
[FRED/ALFRED v1 API-key contract](https://fred.stlouisfed.org/docs/api/api_key.html),
[observation response](https://fred.stlouisfed.org/docs/api/fred/series_observations.html),
[real-time period semantics](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html).

## BEA NIPA, SRC-05

`BEANIPAFileImporter.import_bytes(raw, query, retrieved,
evidence_mode="OWNER_SUPPLIED")` accepts `BEANIPAQuery(table, series_id, unit,
unit_multiplier, start, end, declared_vintage=None)`. It validates NIPA GetData
request metadata, table, selected series, annual/quarterly/monthly periods,
metrics, units, scale, missing values and duplicates. Comma-grouped numerical
values are parsed strictly. Other series may remain in the supplied table;
only the explicitly selected series and date range are normalized.

The BEA response can echo its UserID. The importer refuses unredacted UserID
fields or parameter pairs anywhere in the document, other credential fields,
and recognizable credential-bearing URLs. UserID must be omitted or exactly
`[REDACTED]`. These retained bytes are therefore explicitly the owner's sanitized
export, not the original unredacted HTTP payload. Arbitrary secrets cannot be
discovered reliably from content alone; credential-free export preparation and
provenance remain the owner's responsibility.

A declared vintage is kept as an unverified owner claim. Ordinary current exports
are labeled `LATEST_AT_EXPORT`. Publication and historical availability stay
unknown; current revised values are never labeled historically available.
Selected economic periods and owner-declared vintages after retrieval are
rejected. Same-day claims remain unverified and are never promoted to availability.
Only NIPA is implemented in this slice; other BEA datasets need separate parsers.
The reviewed guide documents GET with UserID in the URL; no documented header or
POST-body alternative was found. This is why live API transport is blocked while
the concrete file parser remains useful.
[BEA API guide, April 2026](https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf).

## Validation and remaining integration

The focused suite currently has 95 passing offline tests, 91.43% combined statement
and branch coverage, and clean Ruff and strict mypy results. It checks revisions,
temporal uncertainty, release identities, units, pagination, malformed JSON,
credentials, HTTP 401/403/404/429/5xx, redirects, timeout, DNS/TLS/byte bounds and
failure retention. Fixtures are synthetic contract examples, not empirical data.
Authenticated FRED verification remains `BLOCKED_EXTERNAL`; BEA/ALFRED API
transport is intentionally absent. No BLS vintage archive extension, complete
G17 table/history loader, research evaluation or source approval is included.

One genuine credential-free G17 request succeeded on 2026-10-05 at
06:41:44.996546 UTC. It retrieved 158,492 bytes and normalized six summary levels;
the diagnostic took approximately one second and made no retry. The candidate
source existed before acquisition. Ignored local evidence is under
`.tools/macro-g17-proof/`, including `summary.json`, the exact source snapshot,
environment, configuration, governed SOURCE/DATASET records, lineage, raw payload
and raw-capture metadata. The source remains `CANDIDATE`, the dataset `PENDING`.
This was a software diagnostic, not a historical trading or research evaluation.

- Raw SHA-256: `942d1af6fee47490fac30ec7cedf5a4587e3e70bd59c0cef96c1ab1e641bcf58`.
- Capture SHA-256: `da34f4b82624d41becb2f8e45c2e55a72141c9ffbb5bbce8ddb3da9c147de5bc`.
- Exact source snapshot SHA-256: `5ebed4d99f6603befd960681b83abd356711ba8a0962f2bca493d46f93ca2a23`.

That immutable diagnostic snapshot predates the independent-review corrections
to the BEA and ALFRED import timeline checks. Its retained evidence describes the
code actually used for the G17 request; no live request was repeated afterward.
