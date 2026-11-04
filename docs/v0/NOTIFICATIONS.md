# Durable local inbox and optional Telegram protocol

The local inbox operates without any external service or credential. This slice
adds no actual account, persistent external configuration, Telegram send, SMS,
broker order, research approval, or scientific claim. Telegram's real connection
test remains `BLOCKED_EXTERNAL`. All transport evidence is offline software
evidence. Existing paper engine and broker files were left unchanged.

## Application contract

`NotificationStore(application_sqlite_path)` creates only additive `qhn_*`
tables. It does not take over the database application ID, user version or journal
mode. Owner-scoped methods are `publish`, `get`, `inbox`, `mark_read`,
`configuration`, `configure`, `delivery`, and `audit`. The host passes the
authenticated principal's owner identity; it must never trust a request-body owner
ID. Readers may list/get/mark their own inbox. Publishing, configuration, and
external-send authorization remain trusted host/owner operations.

`Notification` has only notification ID, dedupe key, kind, severity, mode, title,
body, UTC creation/expiry, and optional existing experiment reference. There is no
raw error, configuration, credential, URL, arbitrary metadata or binary field.
Title/body are bounded plain text; controls, surrogate characters, URL strings,
recognizable token/credential assignments, and Telegram token shapes are refused.
This validation cannot classify every possible unlabelled secret: the host must
generate event text from safe templates and fixed error codes, never forward raw
exceptions, source responses, configuration dictionaries, or vault content.
The web UI must render text safely rather than interpret HTML. The optional
experiment ID is a reference; the host verifies its permanent identity and access.

The allowed modes are SYNTHETIC, REPLAY, LOCAL_PAPER, BROKER_PAPER and SYSTEM.
Synthetic diagnostics are visibly marked. `DELIVERED_LOCAL` means stored in the
inbox; it never means externally delivered. Events remain visible with their
actual local status if expired or rate limited. The host shows Telegram as not
configured/disabled separately, without inventing an external successful send.

Events are immutable exact canonical bytes with SHA-256 checks. Exact duplicates
return the same stored entry; conflicting event ID/dedupe-key reuse fails. Read
receipts are independently immutable/idempotent. Local publication is limited to
30 delivered events per owner per rolling minute. Expired or rate-limited events
are retained with their reason; they are not silently retried later. Creation
cannot be in the future, timestamps must lie in 1970–2200, expiry is at most seven days after creation, and backward
owner audit time fails atomically. List pages are at most 100 records.

## Configuration and credential profile

`TelegramConfig` contains owner ID, monotonic revision, `VaultReference`, numeric
allowed chat ID, and enabled flag. Only one fixed Telegram provider is accepted;
usernames, arbitrary endpoints and target URLs are unsupported. Configuration
changes use expected-revision CAS and append immutable history. Chat IDs are
private targeting data, kept out of object representations; they are not bot
credentials. The bot token never enters the inbox database or delivery content.

`telegram_profile_schema()` returns a closed JSON schema for the root vault
integration: `bot_token` (bounded, write-only) and `allowed_chat_id` (numeric string).
The trusted resolver exposes the existing synchronous
`with_secret(provider, account, slot, consumer)` interface; the consumer checks the
decrypted profile's exact fields and chat ID against the frozen configuration.
The token is consumed only in memory. The current root vault's
`PAPER_OR_READ_ONLY` purpose does not describe message sending: root must add and
review a correctly named notification purpose/profile rather than mislabel this
authority. Root owns owner-role checks, account disablement, vault revocation and
configuration UI. Real `CredentialVault.with_secret` serializes use/revocation;
this slice does not modify that security boundary.

## Narrow Telegram token-path policy decision

**Proposed protocol exception; root decision/review required before product
enablement.** The official Telegram protocol places the bot token in an HTTPS
request path. Its documented POST support moves message parameters into the body,
but does not remove the token from that path. This conflicts with the mission's
generic no-secret-in-URL rule. The implementation does not silently permit secret
URLs elsewhere.

The proposed exception allows only the fixed `api.telegram.org` hostname and
`POST /bot<token>/sendMessage`. The token-bearing path is constructed only at the
native HTTP call in an explicitly enabled disposable child process. It must never
enter URL logging, exception serialization, capture, telemetry, database,
configuration exports, command-line arguments, redirect targets, or generic URL
tools. TLS validates the fixed hostname against a pinned public DNS address;
proxies, custom hosts, redirects and local Bot API servers are unsupported. The
message body contains only fixed plain-text fields, the exact allowed chat ID,
disabled link previews, and protected content. Paid-broadcast options are absent.

The default typed policy is `TelegramPolicy.DISABLED`. Only the exact
`TelegramPolicy.REVIEWED_V0_TOKEN_PATH` enum object is accepted; an arbitrary
decision string or a serialized enum value is refused. This is a trusted-host
capability, not a signature or proof that a decision was approved. Root must record
and review the narrow policy decision before injecting it, and must never create
the capability directly from user JSON. `FixedTelegramHTTPS` independently
defaults to network disabled. No real invocation of that transport was performed.

## Explicit send authority, uncertainty and limits

`TelegramService.send(owner, notification_id, SendAuthorization)` requires a
host-issued authorization bound to owner, exact notification digest, configuration
digest and message-body digest. Its purpose is `EXPLICIT_TEST` or
`EXPLICIT_EVENT_SEND`, with an approval interval no longer than 30 seconds. Test
authority requires a TEST event. The native transport independently checks the
typed policy, token shape, enabled configuration, event expiry and authorization
immediately before the HTTP call. No scheduler or research code issues sends.

Before possible I/O the application SQLite transaction inserts an immutable send
attempt and `UNKNOWN` receipt. The original configuration/chat target and exact
authorization evidence are frozen. A unique `(owner, notification_id)` allows at
most one attempt; another authorization, concurrent worker, restart, or later
reconfiguration cannot cause a second send or retarget the old attempt. A changed
or disabled configuration observed before wire access produces a blocked result.
An already in-flight request cannot be recalled by subsequently disabling a
profile; root serializes authorization/revocation through its account/vault
boundary and reports this limit honestly.

Success requires a valid Telegram response with the expected chat ID, exact text
and bounded message ID. Refusals, blocks, expiry and rate limiting are distinct
states. Timeouts, process crashes, malformed/ambiguous responses or missing vault
access after reservation preserve UNKNOWN. Telegram does not provide this adapter
with an idempotent send identifier or reliable client-ID lookup; UNKNOWN therefore
never automatically retries. An operator must assess it externally. A new explicit
message is a separate action and could duplicate a previously unknown delivery.

SQLite `BEGIN IMMEDIATE` gates sending to at most one attempt per chat per second,
20 attempts per chat per rolling minute, and 25 total attempts per rolling second
within the shared application database. Refused attempts count conservatively.
No automatic HTTP-429 retry or paid broadcast exists. Counts apply across owners
sharing the same chat; separate application databases cannot share these limits.

The inbox permits at most 10,000 events, 10,000 configuration revisions, and 50,000
audit rows. Each event/configuration/authorization canonical payload is at most
8 KiB; each event has at most one send attempt and two receipt revisions. Append
triggers, owner checks, payload hashes, attempt fingerprints, linked delivery
receipt hashes, and owner audit hash chains detect accidental corruption and
conflicting writes. They do not protect against a privileged host owner rewriting
the entire database and recomputing hashes. Capacity failure rolls back the whole
operation; no unjournalled send is permitted. Root owns retention/export policy;
the adapter deletes no existing work. Normal SQLite application backup includes
all tables, with an exercised restore/read proof.

HTTP replies are limited to 64 KiB, IPC replies to 1 KiB, socket operations to five
seconds, and the disposable-process response deadline to 20 seconds, with up to
five seconds of termination/join cleanup. The shared reviewed native resource
helper applies a 256 MiB process-memory limit and five CPU-second limit before
TLS; Windows uses a one-process kill-on-close Job Object, Linux uses address-space,
CPU and zero-core-dump rlimits. Failure to establish limits blocks the request.
Unreaped child/reader or handle cleanup failures produce explicit
`UNKNOWN / PROCESS_REAP_FAILED`; neither pipe cleanup is skipped by a child-close
exception. These resource limits do not establish a host security sandbox.
Raw reply text and provider descriptions are never retained.
Credential reflection, including JSON/URL-decoded echoes, is refused. Parent/child
exceptions become fixed safe result codes; no URL or token is serialized. The
native transport has no redirect or retry path.

## Primary documentation and evidence

Reviewed on 2026-10-05: [Telegram Bot API request format and response contract](https://core.telegram.org/bots/api#making-requests),
[sendMessage parameters](https://core.telegram.org/bots/api#sendmessage), and
[Telegram limits FAQ](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this).
These sources establish protocol details, not account eligibility or successful
delivery in this environment.

Offline tests cover SQLite persistence/backup, exact dedupe, owner isolation,
read receipts, rates/expiry, configuration CAS, rollback/resource caps, stored
corruption, explicit authorization, fixed chat binding, unknown-send restart,
concurrent attempts, configuration races, fake socket/TLS/DNS responses, and real
disposable-process completion/timeout with an offline worker. Real Telegram sends,
root UI/runtime/vault integration and independent review remain separate gates.

The corrected isolated author suite passed 126 tests with `-W error` in 10.73
seconds and 94.88% combined statement/branch coverage. The native test starts via
the actual `quant_hunter.web.main` module, establishes the shared OS limits,
creates a real verifying SSL context/MemoryBIO handshake without sockets, and
proves a 300 MiB allocation is refused under the 256 MiB cap. Further tests prove
oversized IPC, stalled worker, unavailable limits, failed kill/close/join, and
unreaped reader paths remain safe and explicitly uncertain. Root's broader
regression and acceptance of the protocol exception remain separate evidence.

Subsequent independent native review identified an initial-join exception that
could skip a later kill/reap attempt. The mirrored broker/Telegram correction
now attempts termination and a second bounded join even after that exception;
all handle cleanup still runs and uncertainty remains `PROCESS_REAP_FAILED`.
The exact join→kill→join regression was added. The combined author broker and
notification gate passed303tests (176broker,127notification) with `-W error` in
31.89seconds. Independent review separately passed10targeted broker tests and
6Telegram cleanup tests, and closed this finding. No network or messages were
sent by these proofs.
