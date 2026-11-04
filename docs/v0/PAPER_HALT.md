# Persistent global local-paper halt

This adapter adds an owner stop barrier to the bounded synthetic local-paper
workflow. It grants no external order, broker, credential or scientific authority.
Existing PaperEngine, accounting and broker packages are unchanged. Item 8 still
owns every experiment and attempt. A stop does not allocate a new experiment.
Current execution source evidence includes the exact halt module. Historical
inspection allows its absence only when the retained original PaperAccess
producer predates that dependency; current execution never uses this exception.

`GlobalPaperHalt(paper, read_resource=...)` exposes `status(user)`,
`halt(user, expected_revision=...)`, `clear(user, expected_revision=...)`,
`has_pending()` and `process_one()`. The host must supply its actual shared
read-resource reservation context; the default refuses proof inspection. The
host scheduler calls this adapter to process at most one protective task. Root
integration owns owner/CSRF routes, UI, the single runtime process lease and
startup recovery. No additional operational database is introduced: tables live
in the existing application SQLite file and participate in its backup.

The trusted callback receives `(actual_actor, paper_id, halt_revision)` for each
heavy proof. Inside its `BEGIN IMMEDIATE` admission transaction it must call
`authorize_reader(db, actor, paper_id, halt_revision)`, then reserve a unique
reader linked to that actual paper queue reservation while enforcing the shared
two-active limit. The helper verifies current actor identity, the immutable active
HALT/task, actual owning paper chain and a stable initialized PAUSED head. It
returns the actual owner/head revision and halt digest; no fabricated owner or
caller-supplied session mapping is used. The native worker slot is released before
proof reads, and the reader is released before any subsequent native command.
Ordinary portfolio inspection keeps normal resource admission. This narrow
existing-task link must not treat a full queue of eight already admitted paper
sessions as a ninth request. Root integration implements and tests the central
linked-reader counting; this adapter does not silently change its caps.
All controls and complete proof-reader lifetimes share `proof_lock(path)`. The
host's linked-reader context also holds this lock through authorization, reading
and release. This prevents a concurrent control from changing the exact paper
revision while its linked reservation is counted. Risk-increasing controls acquire
the full step/halt gate first; protective controls need only the shorter proof
gate and can still queue during an in-flight bar. Lock order is full gate then
proof gate, never the reverse. A denied PAUSE on an already PAUSED session remains
a state refusal after waiting; valid CANCEL/KILL requests remain retained.

The original authenticated HALT issuer remains authorized only for these trusted
protective reads after a role demotion, using its current actual user record.
Another current owner may clear the halt. Ordinary readers gain no cross-owner
portfolio API, and CLEAR always rechecks current owner authority. CREATED and
terminal receipts and ambiguous-state refusals read bounded operational metadata
only; they neither load native/source evidence nor borrow an absent terminal queue.

Every normal PaperAccess step and ACTIVATE/RESUME/RESET_KILL control also checks
the retained stop history. The guard is intrinsic to PaperAccess, so forgetting
to call the global scheduler cannot permit another normal bar. All instances in
one process share a path-keyed reentrant lock. An owner stop waits for the current
bounded bar to finish, then commits the persistent HALT before acknowledging it.
The host's existing single-process runtime lease is required; this lock is not a
distributed multi-process scheduler. PAUSE, CANCEL and KILL remain callable
during a bounded step; their existing operational control queue is preserved.

HALT captures at most 32 verified nonterminal paper heads, including other users'
sessions, in private immutable task metadata. Public status contains only the
global flag/revision; owners additionally see aggregate pending/protected/blocked
counts. No foreign session ID, account, username, experiment or position appears
in this status. Only current owners may stop or clear. Per-session controls retain
their existing actual owner/researcher checks; readers can only read status.

For a session with no experiment and no uncertain initialization, protection
returns it to CREATED without evaluation. Explicit activation is required later.
For an initialized session, protection uses the same real local PaperEngine KILL,
cancel-request and cancel-confirm commands, retaining native command IDs and
workflow step receipts. It releases reservations and leaves the session PAUSED.
It does not liquidate positions or alter cash, fills, inception equity, high-water
marks, drawdown baselines or scientific attempts. A pending user cancellation is
preserved; a pending reset is replaced by protection. Terminal sessions are
labelled `TERMINAL_NOT_RUNNABLE`: they cannot resume, but this label does not claim
that a failed account's outstanding local orders were successfully cancelled.

An ambiguous/crashed step is not resubmitted. The stop remains active and its
task is BLOCKED until the session's existing explicit reconciliation or cancel
path resolves it. The protective worker can adopt an already retained verified
native outcome without issuing commands again. Startup calls ordinary paper
recovery first; clean sessions pause, unknown operations remain ambiguous, and
the persistent global flag is checked before any normal work. Clear requires
matching retained protective receipts and fresh verification of their actual
current session/native state under host read admission. A final transaction
rechecks revisions and current owner role. Clear never resumes or unkills a
session; reset/reconciliation and explicit per-session resume remain separate.
Each CLEAR event retains the exact per-task receipt digests. Historical event
verification dereferences those proofs, so deleting or replacing the proof after
clear cannot silently leave a verified stop history.

Control events alternate HALT/CLEAR, are canonical JSON, hash chained, UTC timed
and immutable. There are at most 65 controls; the final available record is
reserved for HALT. Each captured task permits at most eight immutable proof or
blocked receipts of at most 2 KiB; each control is at most 16 KiB. Repeated blocked
heads do not retry until their actual workflow revision changes. Occupied worker
slots leave work pending without adding retry receipts. At exhaustion, protection
or clear refuses and the global halt remains active. Paper event headroom reserves
six records for protection while preserving the existing 600-event hard bound.
All native processing still uses the atomic shared two-resource admission check;
no SQLite transaction is held during numerical work or proof inspection.

The focused tests exercise actual SQLite, canonical Item 8 fixtures and Decimal
accounting. They cover cash/position/cost preservation, equity/FX cancellation,
concurrent step and activation races, restart, command-interruption reconciliation,
shared resource limits, role/CAS/privacy rules and corrupt/immutable histories.
These are software safety proofs on synthetic fixtures. They do not establish
market profitability, broker connectivity, live host protection or scientific
promotion. Final exact test/review counts are recorded with the integration
checkpoint, rather than inferred from this implementation description.
