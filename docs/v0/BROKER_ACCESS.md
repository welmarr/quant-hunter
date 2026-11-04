# Private paper broker product boundary

This adapter exposes owner configuration, an explicit bounded account read and
an offline protocol demonstration. It adds no external order route. Real
authenticated broker smoke remains `BLOCKED_EXTERNAL` until the owner supplies
paper credentials and deliberately requests the read test. No real account,
credential, network request, message, purchase or broker order was used to build
or test this slice. Existing official endpoint contracts remain those documented
in `PAPER_BROKERS.md`; geographic/account eligibility is not inferred.

## Public contract and host integration

`BrokerAccess(state, paper, objects, private_root, application_root, *,
read_transport=None, resource=fail_closed)` shares the existing application
state and exact `PaperAccess.lab.objects`. Root owns runtime construction, the
authenticated owner/CSRF boundary, shared two-resource admission, cumulative
disk allowance and UI. The injected `resource(user, operation)` context must
reserve/release the shared work slot for `BROKER_ACCOUNT_READ`,
`BROKER_OFFLINE_PROTOCOL` and `BROKER_EVIDENCE_READ`; its default refuses work.
No SQLite write transaction is held during vault consumption, protocol work or
evidence verification. Current owner identity is checked again after admission,
inside operational write transactions and immediately before account transport.

Methods are `status`, `configure`, `revoke`, `test_connection`, `dry_run`,
`operations`, `get` and `evidence`. Every method is owner-only and every result
belongs to that owner. Metadata reads verify operational payload/receipt hashes;
they declare `OPERATIONAL_JOURNAL` authority. Explicit `evidence` verifies actual
retained objects and their source/result bindings under resource admission. It
does not rerun a request or award scientific approval.

Routes have prefix `/api/paper-brokers`: configuration/status and profile-schema
GET; `{provider}/configuration`, `{provider}/revoke`, `{provider}/test`,
`{provider}/dry-run` POST; operations list/detail GET and
`operations/{operation_id}/verify` POST. Providers are exactly `ALPACA`/`OANDA`.
Bodies are closed JSON, bounded to 4096 bytes; duplicate fields, extra fields and
validation errors are refused without reflecting submitted values. All writes
require an explicit owner/CSRF action. There is no order-submit/cancel/replace
HTTP capability in this product adapter.

## Private configuration and account reads

Profiles require exact provider account ID, key/optional secret, explicit
`ALPACA_PAPER` or `OANDA_PRACTICE` credential origin, `paper_only_confirmed=true`
and an expected revision. Origin is owner-asserted, not independently proved by
the key's format. Native transport still pins only the reviewed paper/practice
host and the client requires exact returned account identity. Neither a live
origin nor arbitrary endpoint is accepted.

Secrets are encrypted only by the existing `PAPER_OR_READ_ONLY` vault in the
separate `private_root/paper_brokers` namespace. Application profiles contain
unique vault references, account identity and revision, never key/secret.
Status masks account and credentials. CAS prevents stale overwrite; failed CAS
may retain an unused encrypted slot. Revocation commits a disabled profile
before revoking that slot. Each profile allows at most 64 revisions, reserving
the final revision for disabling. The cumulative 1000-profile-record bound also
reserves a future disable record for every currently enabled head.

Read testing is GET-only: one Alpaca account request or OANDA account-list plus
summary, at most two responses and 2 MiB cumulatively. Native transport retains
its deadline/TLS/DNS/host/redirect/OS-resource controls. Requests with a mutation
body or risk authorization are refused by the wrapper. Secrets never enter a
URL. Reflection checks run before retaining raw bytes, including malformed
escaped JSON. Unknown response/error bodies cannot reach user error messages.
Safe raw bytes and capture metadata retain the operation ID, owner, profile
revision/digest, fixed host/target/status and actual retrieval time. A profile
change during the response prevents a successful account-read claim. Injected
offline transports are labelled `RECORDED_FIXTURE`; only the actual configured
native transport can label `PRIVATE_PAPER_ACCOUNT_READ`. A read never authorizes
an order.

## Offline risk-to-protocol proof

`dry_run(owner, provider, paper_id, expected_revision=...)` requires the real
owned paused session, actual RUNNING Item8 attempt, current source/environment
binding and exact report/native snapshot agreement. Public
`PaperAccess.execution_snapshot` also checks one active reservation, strategy
identity, remaining quantity, order state, instrument/calendar, quote freshness,
kill, health and reconciliation. This accessor neither creates a reservation
nor grants a network capability.

The adapter constructs the actual reviewed `OrderIntent` and mandatory
`RiskAuthorization` from that reservation. It invokes `PaperBroker.submit` and
the durable `SubmissionJournal` against a fixed in-memory fake server. This path
has no vault access and no configurable/network transport. Synthetic account
identities are deterministically owner-specific. The canonical synthetic equity
symbol `SYNTH_EQ` has an explicit fixture-only alias `QHSYNTH`; FX uses `EUR_USD`.
The alias, authorization, snapshot, acknowledgement and exact fake request/reply
bytes are retained. This is a protocol fixture acknowledgement, not a broker
fill or account smoke. Cash, positions, orders and economic fills in PaperEngine
remain unchanged. No additional research attempt or parameter search occurs.

Operation identity binds owner/provider/session/workflow revision. A separate
immutable claim binds the actual reservation order to at most one demonstration
per provider, even across pause/resume or another workflow revision. The native
journal independently enforces its permanent client-order uniqueness. An
interruption after reservation stays `UNKNOWN`; another caller or restart reads
that state instead of resubmitting. There is no automatic retry.

Before accepting success the adapter verifies the same paused workflow and
native snapshot again. A stale result retains its partial proof but reports
failure. Proof verification binds operation/owner/provider, exact snapshot
digest, retained workflow report, request/reply objects and a retained source
snapshot of the broker implementation plus the lab environment digest. These
are software/reproducibility artifacts, not empirical profitability evidence.

## Persistence and bounds

Append-only `qhb_profiles`, `qhb_operations`, `qhb_receipts` and `qhb_dry_claims`
tables live in the application database. Up to 1000 total operations are allowed;
request/result metadata is at most 16 KiB each, profiles at most 4 KiB. Pending
operations have an immutable start record and no completion receipt, visibly
`UNKNOWN`. There is no state rotation or history deletion at exhaustion.

The native broker journal uses the exact separate filename
`paper-brokers.sqlite3`, retaining its format identity, 32 MiB database bound,
32 account-bindings and 2000-action limits. Root must include that exact file in
private backup/restore verification. Vault paths and credentials are excluded
from ordinary exports and code backups; retained account evidence remains
private to its owner.

Proof documents are at most 2 MiB, fake request/reply objects at most 16 KiB each
and four exchanges, code source objects at most 256 KiB each. Explicit evidence
reads enforce bounded reads before accepting bytes and verify content hashes.
These per-operation bounds supplement the host's cumulative disk quota; the
resource callback must check that quota before admitting work.

Focused tests exercise both actual registered equity/FX paper reservations,
no-book-change arithmetic/state comparisons, unknown/restart behavior, stale
and parallel actions, configuration races, disable headroom, ownership,
secret-redaction faults, HTTP failures, malformed JSON, evidence corruption and
closed ASGI routes. Independent review, root integration and the full regression
gate remain separate requirements.

Peer review tightened verification beyond merely matching object hashes.
Successful account reads require the complete provider-specific capture set;
completed submission receipts require a proof. Every capture binds the exact
historical profile revision and digest, fixed GET sequence and returned account.
The existing account parser normalizes those retained bytes through an internal
read-only replay transport with synthetic credentials; it cannot make HTTP calls
or consume the configured vault. Its result must equal the retained account.

Offline proofs bind the actual immutable reservation claim and native journal
request/submission. Fixed provider/method/target/status sequences, request bodies
and acknowledgement fields must agree with that reservation. The historical
paused report must be the exact report recorded by the verified paper event
chain at that revision, through `PaperAccess.execution_receipt`; an internally
consistent newly fabricated report is insufficient. Exact environment and EXP
identities repeat across the snapshot and implementation; the retained source
archive is verified too. Inspection remains valid after later pause/resume or
session completion and never substitutes today's state for the old snapshot.
Failed/UNKNOWN records retain honest partial evidence without a success claim.
