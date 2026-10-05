# Remaining priority-source adapters

This standalone slice adds concrete parsers for SRC-09, SRC-18, SRC-19 and SRC-20.
Only Sharadar through Nasdaq Data Link and Trading Economics have implemented HTTP
clients. No real key, account, API request, AWS access or purchase was made. Live
authenticated checks remain `BLOCKED_EXTERNAL`. Root integration owns source
registration, rights review, quotas, credential configuration, immutable capture
and catalogue/UI status. Mission catalogue keys are not canonical SOURCE IDs.

| Catalogue | Implementation | External limitation |
| --- | --- | --- |
| SRC-09 Dukascopy | Daily BI5 owner-file importer, bounded LZMA decode | Current documented archive uses AWS Requester Pays; no billing or AWS credentials authorized |
| SRC-18 Sharadar | Nasdaq SF1 header-authenticated paged client, three financial fields | Owner entitlement and Nasdaq key absent; native currency metadata required before research |
| SRC-19 EODHD | Owner-file daily EOD JSON importer | No compatible non-URL REST authentication verified |
| SRC-20 Trading Economics | Header-authenticated bounded calendar client | Owner subscription/key absent; historical consensus availability unverified |

## Common interface and controls

HTTP clients accept `PriorityKey(value)` and an optional injected
`PriorityTransport.send(PriorityRequest) -> EquityResponse`. They expose
`validate_config`, `test_connection`, `list_capabilities`, `fetch_range`,
`normalize`, `validate_batch` and `health`. Keys and request targets are hidden
from representation, never loaded from environment variables and never placed
in URLs. Responses reflecting keys in plain, JSON-escaped or URL-escaped text
are refused before retaining a page. Exceptions expose sanitized codes.

File importers expose `import_bytes`, `normalize`, `validate_config`,
`validate_batch`, `list_capabilities` and `health`, with a separate blocked
transport reason. They have no pretend fetch method. File imports retain exactly
the supplied bytes; their symbol/currency bindings are owner declarations where
the provider file lacks those fields. Rights and provenance must be supplied
through the root governance workflow before use.

`PriorityBatch[T]` contains catalogue key, typed records, exact-byte SHA-256 raw
pages, evidence mode and limitations. Default HTTP transports use `HISTORICAL_REAL`;
injected transports use `RECORDED_FIXTURE`. File imports use `OWNER_SUPPLIED` or
`RECORDED_FIXTURE`. None of these labels grants source, quality, coverage or
scientific approval. Coverage is explicitly incomplete. Every normalized record
keeps availability unknown and PIT eligibility false.

Requests are fixed to `data.nasdaq.com` SF1 or `api.tradingeconomics.com` calendar
paths. The native transport validates all resolved addresses as public, pins one
address into TLS while checking the official hostname, and rejects arbitrary
hosts, redirects, duplicate query parameters and compressed HTTP bodies. It
uses a resource-bounded child with a twenty-second parent wall deadline covering
startup, DNS, connection, TLS, headers and body, followed by bounded termination
and reaping. Socket/body timeouts are additional limits; no retry is automatic.
See SOURCE_HTTP_BOUNDARY.md for the exact process contract.
Each raw response is capped at 2 MiB. JSON duplicate keys and embedded credential
fields/URLs fail. Financial JSON numbers use exact Decimal parsing with bounded
digits/exponents; missing values never become zero.

## Dukascopy, SRC-09

`DukascopyDailyImporter.import_bytes(raw, DukascopyQuery(pair, day, point_scale),
retrieved, evidence_mode="OWNER_SUPPLIED")` implements the documented daily BI5
record shape. Only nine explicitly mapped FX pairs are accepted: EURUSD, GBPUSD,
AUDUSD, NZDUSD, USDCHF, USDCAD, USDJPY, EURJPY and GBPJPY. The caller must supply the
correct scale: 100,000 for the first six, 1,000 for the JPY pairs. Non-FX symbols
and hourly timestamp conventions are refused.

Before decoder allocation, the importer checks the LZMA-alone properties,
dictionary size and declared output size. It limits compressed bytes to 2 MiB,
dictionary to 8 MiB, decoder memory to 16 MiB, decoded output to 16 MiB and rows
to 100,000. Truncated streams, trailing data, incomplete records, non-finite
volumes, crossed/zero quotes and unordered times fail. Legitimate same-millisecond
records retain their original sequence. Unsupported headerless raw LZMA or XZ
containers are refused rather than assigned guessed filter properties.

The source format describes UTC-day millisecond offsets, big-endian ask/bid
integers and float32 side volumes in millions of base currency. The importer
retains those volume values as decoded floats. These are broker-specific quotes,
not global FX volume, guaranteed executable liquidity or forwards.
[Official Dukascopy export and BI5 guide](https://www.dukascopy.com/wiki/en/development/data-export/).
That guide currently requires AWS credentials and Requester Pays. No free FX
smoke was attempted; an owner-provided lawful file remains the supported input.

## Sharadar through Nasdaq, SRC-18

`SharadarConnector(key=None, transport=None)` accepts
`SF1Query(ticker, dimension, start, end, max_pages=5)`. It requests only ticker,
dimension, `calendardate`, `datekey`, `reportperiod`, `lastupdated`, revenue,
net income and assets from `/api/v3/datatables/SHARADAR/SF1.json`. Date bounds
apply to `datekey`, span at most 3,660 days and use at most five 1,000-row pages.
The parser binds columns by name, checks declared column types and row identity,
rejects cursor loops and duplicate/changed primary identities across pages, and
sorts its returned records because the provider does not promise ordering.

The API supports AR and MR annual, quarterly and trailing-year dimensions.
Filing-index, calendar-normalized period, fiscal report period and database update
dates remain separate. Current AR acquisition is not authenticated historical
delivery; MR restatements do not replace prior retained responses. The selected
financial fields are explicitly labeled native currency unverified. Currency
metadata and as-of delivery evidence are required before research admission.
[SF1 dimensions and request contract](https://data.nasdaq.com/databases/SF1/documentation?anchor=see-also),
[provider field definitions](https://sharadar.com/docs/fundamentals).

Nasdaq's official Python SDK attaches `x-api-token` in its shared connection
layer. This client uses that documented provider implementation and does not
copy query-key examples. It does not implement the distinct newer direct
`api.sharadar.com` API or infer that a direct-Sharadar subscription grants Nasdaq
entitlement.
[Official Nasdaq SDK authentication](https://github.com/Nasdaq/data-link-python/blob/main/nasdaqdatalink/connection.py),
[official cursor usage](https://github.com/Nasdaq/data-link-python/blob/main/FOR_DEVELOPERS.md),
[Tables API paging parameter](https://static.quandl.com/Quandl-datatables-api.pdf).

## EODHD, SRC-19

`EODHDFileImporter.import_bytes(raw, EODQuery(symbol, currency, start, end,
declared_listing_status="UNKNOWN"), retrieved)` accepts at most 5,000 daily JSON
rows over a 3,660-day date envelope. It enforces positive prices, OHLC
relationships, integer volume, exact dates, chronological uniqueness and
declared symbol/currency syntax. The EOD response lacks symbol/currency fields;
the record explicitly identifies those bindings as owner declarations.

Raw OHLC, split-and-dividend-adjusted close and split-adjusted volume remain
distinct. Adjusted history can change in later exports; each supplied version
retains its own bytes and values. No split-adjusted OHLC is fabricated from an
adjusted close. Delisted symbols such as the provider's `_old` convention are
accepted with an explicit declaration, but this does not establish an unbiased
historical universe, delisting dates or ticker continuity.
[Official EOD fields and adjustment semantics](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes),
[official delisted-symbol guidance](https://eodhd.com/financial-academy/financial-faq/survivorship-bias-free-financial-analysis).

The verified REST examples use `api_token` in URLs. Header authentication claims
from third-party material were not adopted. EODHD's own MCP implementation says
its outgoing REST requests still use that query token; incoming MCP header
support is not evidence of REST header support.
[Provider-maintained MCP authentication explanation](https://github.com/EodHistoricalData/EODHD-MCP-Server/blob/main/README.md).

## Trading Economics, SRC-20

`TradingEconomicsConnector(key=None, transport=None)` accepts
`CalendarQuery(country, start, end)` for one country and at most seven elapsed
days. Its one fixed GET uses the documented raw `Authorization` header value,
without adding a Bearer prefix. A response with 1,000 rows is refused as possibly
truncated; no undocumented pagination is invented.
[Official authentication](https://docs.tradingeconomics.com/get_started/),
[country calendar](https://docs.tradingeconomics.com/economic_calendar/country/),
[provider limits](https://docs.tradingeconomics.com/get_started/rate-limits/).

Records keep actual, previous after revision, previous before revision, consensus
forecast and provider forecast as separate source strings with their unit and
currency. Missing values stay missing; suffixes such as K or percent signs are
not converted through guessed unit rules. REST field definitions govern the
before/after revision mapping. `Date` is interpreted under the provider's stated
UTC convention. `DateSpan` retains exact versus estimated scheduling. The raw
last-update timestamp remains separate without an invented timezone assignment.

A retrieved forecast is a current snapshot, not proof of consensus known before
publication. Release schedule is not observed dissemination; all availability
fields remain unknown. Success does not authorize event-surprise research without
properly timestamped prepublication snapshots.
[Official calendar field semantics](https://docs.tradingeconomics.com/economic_calendar/schema/).

## Validation status

The focused synthetic suite has 133 passing tests and 97.49% combined statement
and branch coverage. Ruff and strict mypy pass. Tests cover actual socket/TLS contracts
using doubles, HTTP 401/403/404/429/5xx, redirection refusal, timeouts, private DNS,
oversized responses, malformed JSON, escaped secret echoes, pagination loops,
revision preservation, temporal separation, wrong units and hostile compressed
metadata before allocation. No empirical or professional certification is claimed.
Full regression and independent review belong to root integration.
