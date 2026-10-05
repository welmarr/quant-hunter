# SEC and Alpaca data clients — bounded Phase B slice

Status: implemented HTTP clients with offline contract tests; both live checks
remain `BLOCKED_EXTERNAL`. SEC requires the owner's actual configured contact
identity. Alpaca requires explicitly supplied paper-account or verified read-only
market-data credentials, source rights and feed authorization. No account was
created, credential obtained, authenticated call made or purchase performed.
The root integration owns catalogue/UI updates and the governed capture facade;
these standalone modules do not allocate datasets or approve sources.

## SEC EDGAR, catalogue SRC-01

`SECConnector(identity=None, transport=None)` exposes `validate_config`,
`test_connection`, `list_capabilities`, `fetch_range`, `normalize`,
`validate_batch` and `health`. `SECIdentity(organization, contact_email)` must
contain the owner's deliberately supplied contact, never an address inferred
from Git or a placeholder used for a real request. Contact fields are hidden
from representation and used only in the User-Agent request header.

`SECQuery(cik, start, end, resource="submissions")` accepts a zero-padded ten-digit
CIK and an inclusive filing-date range of at most 3,660 days. One request retrieves
the current recent-submissions object and filters its filing dates locally.
Older archive files advertised by SEC are not followed; coverage is explicitly
incomplete. The source accession is preserved exactly, including third-party
filer CIKs. `/A` forms are amendments; the client does not invent their original
filing links. Acceptance timestamp, filing date, reporting date and ingestion
time remain separate. Missing acceptance timestamps remain missing. Acceptance
is not asserted to be dissemination or historical decision availability.

`resource="company_concept"`, with an explicit supported standard `taxonomy` and
`concept`, retrieves one concept's facts across all supplied units. This is a
bounded fact client, not a company-wide XBRL or Financial Statement Data Sets
bulk importer. It retains each accession, filing date, period, unit, fiscal
context, amendment flag and value. It never selects the latest revision to
replace earlier disclosures. Duplicate or contradictory identities fail.

SEC documents unauthenticated submissions and concept JSON endpoints and their
current aggregate nature. Its recent-submissions response is a partial history;
single-concept facts are grouped by units. [Official SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).
SEC requires a declared User-Agent contact and publishes a ten-request-per-second
aggregate limit. Acceptance and public dissemination can differ; post-acceptance
corrections and deletions occur. The root caller must enforce shared quotas
across users/processes and review data reuse for its intended purpose.
[SEC access and fair-use guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).

## Alpaca historical stock bars, catalogue SRC-02

`AlpacaDataConnector(credentials=None, transport=None, allowed_feeds=("iex",))`
exposes the same seven methods. `AlpacaCredentials(key_id, secret_key,
credential_source)` accepts only `PAPER_ACCOUNT` or `READ_ONLY_MARKET_DATA` as an
explicit configuration declaration. It rejects a declared live-account source.
The declaration is not cryptographic proof of the actual key's scope; a secure
configuration workflow must verify provenance before activation. No credential
is read automatically from environment variables or another local application.

Official documentation supports market-data use with paper accounts and identifies
IEX as the paper-only account's data entitlement. This does not establish any
particular person's account eligibility or SIP entitlement. The data endpoint is
`data.alpaca.markets`; neither live nor paper broker hosts are implemented.
[Paper-account documentation](https://docs.alpaca.markets/us/v1.4.2/docs/paper-trading),
[market-data authentication and entitlement FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).

`AlpacaBarQuery(symbol, start, end, feed, timeframe="1Day", page_size=1000,
max_pages=5)` requires explicit UTC datetimes and an explicit `iex` or `sip` feed.
The range is inclusive and at most 366 days. Only one symbol and `1Min`/`1Day`
are supported. SIP additionally requires caller authorization through
`allowed_feeds`; neither feed is silently substituted after a failure.

Requests pin `adjustment=raw`, `asof=-`, `currency=USD` and `sort=asc`. Disabling
symbol mapping avoids silently relabeling historical symbols as current names;
it does not provide a permanent instrument identity or delisting history.
Bars retain decimals, provider UTC timestamps, feed, timeframe, OHLC, volume,
trade count and nullable VWAP. Their timestamps are not availability times.
Daily session close times are not guessed. Publication, revision and historical
availability remain unknown; no record is point-in-time eligible by this client.

The official bars endpoint specifies inclusive query bounds, pagination and
explicit raw/adjusted modes and symbol-mapping controls.
[Alpaca bars reference](https://docs.alpaca.markets/us/reference/stockbars).
IEX is a single venue; SIP represents consolidated data. Licensing, access,
retention, redistribution and per-user rights still require verification for
the configured account and intended use. No fixed subscription price or full
coverage guarantee is embedded in the client.
[Feed documentation](https://docs.alpaca.markets/us/docs/historical-stock-data-1).

## Security, bounds and retry semantics

`EquityTransport.send(EquityRequest) -> EquityResponse` permits an injected
contract fixture. With no injection, `EquityHTTPS` actually sends bounded HTTPS
GETs to only the exact SEC or Alpaca read endpoints. Authentication is only in
fixed Alpaca headers. Requests, credentials, contact identities, response bodies,
raw pages and pagination tokens exclude sensitive values from `repr`.
Provider response/error bodies are never included in exceptions or logs.
Responses directly reflecting a supplied credential are refused before retention.
These Python objects remain sensitive in memory; callers must not serialize
credential/request objects with `dataclasses.asdict`, log header dictionaries,
or include secrets in snapshots or captures. The future vault workflow owns
encryption, rotation and permission checks.

No arbitrary URL, broker endpoint, redirect, proxy, compressed response or
automatic retry is supported. DNS resolves once to public addresses and the
selected address is pinned while TLS validates the official hostname. Each
request has a twenty-second parent wall deadline covering child startup, DNS,
connection, TLS, headers and body, followed by bounded termination/reaping.
Socket/body timeouts remain additional limits; each response is capped at
2,000,000 bytes. See SOURCE_HTTP_BOUNDARY.md for the exact process contract.
SEC permits at most 2,000 submissions or 5,000 facts per response. Alpaca permits
at most five pages of 1,000 bars each, with repeated tokens and duplicate or
unordered bars rejected. Partial pages remain accessible as `last_pages` after
a later parse/pagination failure; the failure is not a successful complete batch.
Numeric HTTP Retry-After metadata is returned through sanitized errors, without
sleeping or changing the requested feed.

Retries are explicit whole-query acquisitions, never hidden loops or in-place
corrections. Raw pages carry SHA-256 identities and retrieval timestamps so the
root immutable facade can deduplicate bytes and retain a new capture attempt.
Page-bound exhaustion fails instead of returning a success marked complete.
Empty successful responses contain zero observations; they do not establish
data coverage. Neither pagination exhaustion nor connection success is quality
approval, source approval, a scientific result or an execution-price claim.

## Verification and remaining integration

`tests/test_v0_source_equities.py` uses synthetic JSON and an injected HTTP
transport, plus controlled socket/TLS doubles for the native transport. It
covers success, 401/403/404/429/5xx, timeouts, redirects, malformed schemas and
numbers, duplicate keys/rows, pagination loops/limits, secret reflection,
header injection, broker-host refusal, private DNS, units/amendments and unknown
availability. Fixtures are `RECORDED_FIXTURE`; a default-client live acquisition
would be `HISTORICAL_REAL`. No SEC or Alpaca live acquisition was attempted.

Official references above were checked on 2026-10-05. Root integration now adds
owner-only encrypted configuration, rights declarations, governed immutable
source/capture/dataset publication, source status and bounded application quotas.
The diagnostic query is one SEC recent-submissions response for a configured CIK
(2025 filing-date window), or one AAPL/IEX daily-bar response (2024-01-01 through
2024-01-05). Candidate identity is allocated before retrieval. All returned
datasets retain pending quality and unavailable historical information timing.
Actual owner configuration and authenticated access remain unverified. Broader SEC archives,
company-wide facts/bulk financial-statement datasets, Alpaca trades/quotes and
additional timeframes are outside this completed client slice, not implicit
capabilities. BLS/ECB client behavior remains unchanged.

The isolated 2026-10-05 check ran on Windows with Python 3.14.7: 93 tests passed
in 0.70 seconds, with 94.84% combined statement/branch coverage across the three
new source modules. Ruff and strict mypy passed on these modules and their test
file. The parent integrator owns the full-suite regression and cross-item gate;
these focused results do not replace that gate. Root review added decimal
bounds and encoded secret-reflection regressions, bringing this targeted module
to 99 passing tests. Final integrated evidence is in TEST_REPORT.md.
