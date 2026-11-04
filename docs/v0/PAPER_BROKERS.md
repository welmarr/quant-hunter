# Bounded paper broker REST adapters

This slice implements offline-tested Alpaca paper and OANDA practice protocol
adapters. It does not connect an account, send an actual order, approve research,
or establish live execution quality. Authenticated broker smoke evidence is
`BLOCKED_EXTERNAL`; no real credentials were supplied or used. All test fixtures
and results are software evidence, not market observations.

## Public contract and supported profiles

`PaperBroker(BrokerConfig, SubmissionJournal, transport=...)` defaults to an
`OfflineTransport` that refuses all requests. `FixedPaperHTTPS` also defaults to
network disabled; an authorized host must explicitly enable it. Construction
performs no network operation. The configuration has no URL or live-host option.

The exact hosts are `paper-api.alpaca.markets` and `api-fxpractice.oanda.com`.
Credentials require the explicit `PAPER_ONLY` purpose. This assertion does not
prove the credential's origin or account eligibility: the host must obtain paper
credentials through its controlled vault/configuration workflow. No live key is
created, connected, or recommended. Credentials are hidden from representations,
put only in authentication headers, and never placed in query strings or bodies.

| Provider | Implemented order profile | Explicit restrictions |
| --- | --- | --- |
| Alpaca | US equities, whole-share MARKET/LIMIT/STOP, DAY, simple orders | No extended hours, fractional shares, option/crypto orders, bracket/OCO/OTO, trailing stops, or streaming |
| OANDA | Currency instruments, MARKET FOK/IOC; LIMIT/STOP GTC; explicit signed units and REDUCE_FIRST/REDUCE_ONLY/OPEN_ONLY | MT4-linked accounts refused; no guaranteed/trailing stops, dependent orders, metals/CFDs, hedging inference, or streaming |

The concrete operations are `account`/`test_connection`, `positions`, `orders`,
`get_order(client_order_id)`, `submit`, `cancel`, `replace`,
`reconcile_submission(action_id)`, and `executions(cursor)`. `capabilities` exposes
the bounded REST profile and blocked authenticated-smoke status. Account reads
verify the expected account ID returned by the fixed paper host; the adapter
does not invent a broker-returned environment flag. OANDA first verifies the
account list and refuses an `mt4AccountID` before using client extensions.

Instrument metadata gates admission: equity asset class/active/tradable status
and documented price grid; FX currency type, trade-unit precision, minimum and
maximum units, and displayed price precision. These checks do not establish
short-sale eligibility, margin capacity, buying power, session admission, a
strategy's position ownership, or economic risk authorization.

## Required execution authority

Every mutation requires a `RiskAuthorization` argument. It binds provider,
account, owner, existing experiment and strategy references, risk revision, and
the SHA-256 of `action_bytes(action, intent, original_client_id)`. Approval and
expiry must be UTC, current, and no more than 30 seconds apart. Expiry is checked
before preflight, before durable reservation, and immediately before the wire
attempt. The HTTP boundary independently verifies authorization and exact body
fields against the frozen action. Changing quantity, side, instrument, price,
time-in-force, or OANDA position policy invalidates the request.

This is a trusted-host capability contract, not a cryptographic signature or a
scientific approval. The host must never deserialize one from user request JSON.
The host must validate permanent references and authenticated ownership, enforce
its atomic reservations, risk/kill/session controls, and issue the capability.
The adapter allocates no research identities and performs no strategy evaluation.
For Alpaca cancellation/replacement, the trusted adapter resolves the broker UUID
from the checked client-ID lookup; the host authorization binds the original
client ID, not a separately signed UUID. OANDA uses the bound `@client_id` path.

## Durable uncertainty and reconciliation

`SubmissionJournal(path)` is a separate local SQLite operational ledger. Before
the first possible wire mutation it commits the exact action and authorization
bytes plus an `UNKNOWN / WIRE_ATTEMPT_RESERVED` receipt. A process crash at that
point cannot cause automatic retransmission. Exact duplicate action IDs return
the existing receipt after normal preflight; conflicting repeats are rejected.
Submit/replacement client IDs cannot be reused with a new approval ID. Owner
bindings persist across restart and are checked on every journal read/write.

The journal uses `BEGIN IMMEDIATE`, foreign keys, full synchronous rollback
journaling, immutable action/receipt triggers, and hash-linked receipt history.
Loads verify payload fingerprints, receipt ordering/hashes, and the head. Limits
are 32 account bindings, 2,000 total actions, 32 receipts per action, 16 KiB per
canonical payload, 4 KiB pages, and a 32 MiB database cap. SQLite resource or
integrity failures must stop the host operation; they are not permission to send
an unjournalled order. This is local integrity/replay evidence, not protection
against a privileged host owner rewriting both the database and its hashes.

Timeouts, malformed responses, inconsistent acknowledgements, ambiguous status
codes, or a lost response remain `UNKNOWN`. HTTP 400/401/403/404/422/429 mutation
responses are recorded as request refusals; no automatic retry occurs. A broker
acknowledgement is explicitly not a final fill. Cancellation acknowledgement does
not assert that a racing fill was prevented. `reconcile_submission` queries by
client ID; a query 404 remains unresolved and never causes resubmission. It binds
the returned instrument, side, quantity, order type, time-in-force, price, and FX
position policy to the original intent. A found order resolves submission
identity, not the entire account or fill ledger. Replacement/cancellation races
still require host reconciliation of original and replacement orders, fills,
positions, and cash before releasing economic reservations.

Preflight failures before journal reservation raise a fixed safe error code; the
host operation-audit layer must retain those failed requests. The adapter journal
does not replace the experiment ledger or local paper engine's risk/account book.

## Bounded transport and evidence

The transport allows only documented fixed paths/methods and tightly bounded
queries. It refuses arbitrary URLs, live hosts, duplicate query keys, redirects
(there is no redirect following), private/reserved DNS results, proxies, and
compressed response bodies. A public IP is resolved and pinned to the socket;
TLS validates the original official hostname. Credentials remain in memory and
an anonymous child-process pipe, never in subprocess command arguments or logs.

Each request uses a disposable child process, a 20-second response deadline,
5-second socket limits, and bounded termination/join cleanup (up to 5 additional
seconds). Responses are at most 2 MiB, requests at most 16 KiB, and paths at most
2,048 characters. There is no retry or hidden pagination loop. The host must
serialize/rate-limit actual calls to provider/account limits and aggregate quota;
this adapter is not a cross-process quota service. No network-enabled deployment
is claimed by the offline tests.

The product-integration audit found that the earlier child had only wall/socket
bounds and that a child-close exception could skip remaining handle cleanup.
The narrow correction establishes the shared native256MiB/5CPU-second limit
before TLS/DNS; Windows additionally limits the job to one process. Failure to
establish those limits prevents all wire work. Child logging and bytecode writes
are disabled. Process termination/close, each pipe close and reader join are
independently guarded; an unreaped child or reader raises fixed
`PROCESS_REAP_FAILED`, preserving economic uncertainty. These are resource bounds,
not a claim of a host security sandbox.

The corrected author gate passed175broker tests with `-W error` in10.96seconds.
New native proof uses the actual `quant_hunter.web.main` spawn entry point, real
verifying SSL/MemoryBIO without sockets, and rejects a300MiB allocation under the
256MiB cap. Offline tests also cover oversized IPC, unavailable limits, stalled
workers and independent kill/close/join/start faults. Independent amendment review
and root-wide integration remain separate gates.

Independent amendment review then found that a failed first join could skip
termination. The final correction independently attempts kill and a second join
after a first-join exception, while keeping `PROCESS_REAP_FAILED`. Its exact
join→kill→join regression and the mirrored Telegram fix passed303combined author
tests (176broker,127notification), `-W error`, in31.89seconds. The peer independently
ran10broker native/cleanup tests and6Telegram cleanup tests and closed the finding.
Root-wide integration remains separate.

Response parsing rejects duplicate JSON keys, invalid numbers, malformed schemas,
impossible fill quantities, repeated identities, pagination loops, and unordered
execution times. Financial values use bounded Decimal conversion. Provider UTC
timestamp strings preserve nanoseconds rather than silently truncating them.
Returned credential reflection is refused before retention, including decoded
JSON escapes and URL escapes. Transport exceptions are converted to fixed codes
without serializing exception text or unchecked response headers.

`last_evidence` contains the latest accepted raw HTTP bytes and digest, UTC
retrieval time, and exact sanitized request metadata bytes/digest. Request and raw
bytes are hidden from representations; credentials are absent. It is cleared
before each request, including failed requests. This per-client in-memory value
is not durable capture of every preflight request: the host must capture required
response/provenance bytes immutably and use separate client instances for separate
operations. The operational journal retains action/authorization evidence, not
raw broker payloads. Private account/position data must never be committed.

`executions` returns only one page. Alpaca uses the documented activity cursor
format and at most 100 FILL activities; type, cumulative/leaves quantities,
execution price and exact transaction time remain distinct. OANDA requires a
numeric transaction cursor, accepts at most 1,000 ordered transactions, and keeps
realized P/L, financing, and commission separate. Its order status alone does not
fabricate filled quantity or average fill price. The host owns durable cursors,
overlapping-page deduplication, complete account reconciliation, and missing-page
handling. Hitting a bound fails rather than silently truncating data.

## Official documentation reviewed

Reviewed on 2026-10-05, without account access or broker requests:

- [Alpaca paper trading](https://docs.alpaca.markets/us/docs/paper-trading): separate paper credentials/host and simulation limitations.
- [Alpaca create order](https://docs.alpaca.markets/us/reference/postorder), [get account](https://docs.alpaca.markets/us/reference/getaccount-1), and [client-ID lookup](https://docs.alpaca.markets/us/reference/getorderbyclientorderid): endpoint and field contracts.
- [Alpaca replace](https://docs.alpaca.markets/us/reference/patchorderbyorderid-1), [cancel](https://docs.alpaca.markets/us/reference/deleteorderbyorderid-1), and [order lifecycle](https://docs.alpaca.markets/us/docs/orders-at-alpaca): asynchronous acknowledgement, price grids, and races.
- [Alpaca account activities](https://docs.alpaca.markets/us/docs/account-activities): FILL fields and timestamp/UUID cursor format.
- [OANDA development guide](https://developer.oanda.com/rest-live-v20/development-guide/): practice host, header authentication, and request/connection limits.
- [OANDA order endpoints](https://developer.oanda.com/rest-live-v20/order-ep/) and [order definitions](https://developer.oanda.com/rest-live-v20/order-df/): request types, signed units, client extensions, MT4 restriction, and order state.
- [OANDA account endpoints](https://developer.oanda.com/rest-live-v20/account-ep/), [account definitions](https://developer.oanda.com/rest-live-v20/account-df/), [primitives](https://developer.oanda.com/rest-live-v20/primitives-df/), and [transactions](https://developer.oanda.com/rest-live-v20/transaction-ep/): identity, precision, timestamps, and transaction polling.

Tests use injected fixtures, fake sockets/TLS, and a real disposable process with
an offline worker. They exercise successful protocol responses, HTTP refusals,
timeouts, hostile response schemas, auth/host refusal, credential reflection,
concurrent duplicate attempts, restart uncertainty, and journal corruption. They
do not certify broker availability, account entitlement, fill realism, profitable
strategies, or readiness for live trading. Root integration, independent review,
the broader regression gate, and host audit/risk/vault controls remain separate.

The final isolated author gate passed 158 tests with `-W error` in 7.42 seconds,
91.28% combined statement/branch coverage, Ruff check/format, and strict mypy over
the package and both test files. Coverage data and test caches stayed on D. This
author result does not claim independent review or root integration completion.
# Independent boundary corrections

Independent offline review found three gaps after the initial author gate.
Authorization is now revalidated immediately before HTTP transmission, after
DNS/TLS setup, so expiry during connection setup sends no order request.
OANDA create/cancel acknowledgments require the exact authorized order type or
ORDER_CANCEL respectively. Missing/contradictory types remain UNKNOWN and cannot
resubmit. Nonempty malformed JSON is refused before raw response retention,
including malformed Unicode-escaped credential reflections; an empty204 cancel
response remains valid.

The corrected full166-test offline suite passes with warnings treated as errors.
The independent reviewer also ran all166 tests successfully. The existing
instrument/units/client/account contradiction fixture was then corrected to
include its otherwise valid MARKET type, and those four checks plus both
positive provider acknowledgments passed again. These facts are software
boundary evidence, not actual account eligibility or external execution proof.
