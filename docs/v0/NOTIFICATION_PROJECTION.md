# Local completion notification projection

`NotificationProjection(NotificationAccess)` supplies an operational recovery
projection over the existing application database. Its only publication action
is the existing `NotificationAccess.record_job`; it never invokes a Telegram
send, opens the vault, executes research, changes a job, allocates a research ID
or replays an experiment. The original jobs remain the authoritative recovery
source. Terminal statuses are `SUCCEEDED`, `FAILED` and `CANCELLED`.

## Runtime contract

Create one projection from the runtime's actual notification access instance.
Call `sweep(current_user, limit=100)` at a bounded idle cadence and on an explicit
inbox refresh. The host must supply the actual current user; each database
transaction rechecks identity and role, including for reader-owned history.
Do not invoke it on every iteration of a tight worker loop. It has no background
thread, network scheduling or implicit notification send.

Each call inspects at most 100 owned jobs. `status(current_user)` returns only
that user's saved projection status and fixed diagnostics. Results include
`status`, `local_delivery_unavailable`, `failure_code`,
`failure_receipt_persisted`, `first_failure`, `last_failure`, `cycle`, `cursor`,
`ceiling`, `cycle_complete`, `scanned` and `projected`.
`projected` counts confirmed terminal notices, including already-existing
idempotent notices; it does not mean newly delivered messages or external sends.
An inbox event can retain the core's `RATE_LIMITED` local classification.

## Cursor and recovery

The additive `qhn_projection` table stores one bounded, hashed operational head
per user in the existing application SQLite database. It is part of that
database's ordinary backup. This table is not a scientific ledger or another
source of experiment status.

Each cycle freezes a maximum owned job primary key and advances in ascending
key order. Primary keys are stable across SQLite maintenance. The next call
after cycle completion begins again from the start, catching a formerly pending
older job and a newly inserted random key behind the cursor. New work cannot
continually displace older work from a newest-100 query. Completion describes
the frozen cycle, not future jobs or a claim that all asynchronous jobs finished.

Publication commits before the cursor. A process interruption in between leaves
the cursor unchanged; the next sweep invokes the deterministic existing dedupe
key and confirms the actual retained event. Concurrent callers use a cursor
compare-and-swap in `BEGIN IMMEDIATE`; a losing caller stops without regressing
progress. The returned event is checked against the selected job status and
experiment link before progress is committed. No arbitrary callback response can
substitute for a retained inbox event.

## Bounds and failure truth

The global scan admission bound is 10,000 jobs. Exceeding it returns
`LOCAL_DELIVERY_UNAVAILABLE` / `JOB_CAPACITY`, without deleting jobs or silently
dropping older failures. Each saved head is at most 4 KiB. SQLite transactions
retain the existing AppState connection timeout; the page count is a work bound,
not a process-enforced total deadline.

Any inbox capacity, integrity or other delivery error stops the page before the
failed job's cursor advances. The operational head retains first and latest
failure receipts with fixed code/cycle/cursor only. Repeated identical failures
do not append unbounded rows. Recovery clears the active-unavailable flag while
retaining those receipts; this deliberately is not a complete error event log.
The inbox core retains its separate immutable publication audit.

Exceptions, credentials, dataset contents and arbitrary error text are never
stored or returned. If corrupt or unavailable SQLite prevents writing a failure
receipt, `failure_receipt_persisted=false` makes that limitation explicit. Stale
or forged identities receive an access error rather than another user's state.
Neither these checks nor successful software tests establish host tamper
resistance, research approval or empirical validity.

## Verification

Focused tests use actual application and notification SQLite tables with
synthetic terminal jobs. They cover more than two pages, delayed old completion,
random-key insertion behind the cursor, restart after publish-before-cursor,
concurrent compare-and-swap, retained and recoverable failures, corruption,
10,001-job admission refusal, owner isolation, reader history, unknown states,
missing actual events and substituted experiment links. Source integration and
the full repository gate remain the root integrator's responsibility.

The final corrected author gate passed 39 tests with warnings treated as errors
in 36.85 seconds, with 98.32% combined statement/branch coverage. Ruff and strict
mypy passed for both source and tests. Independent review reproduced a gap in
the preceding 37-test source: an event payload could substitute another existing
notice ID while retaining its original indexed dedupe/body fields. The corrected
projection also binds the payload notification ID and fixed title; two coherent
rehash regressions retain the exact existing-second-notice case. The independent
reviewer reran its original reproducer plus retained-event and crash/CAS tests:
6 passed in 2.66 seconds with warnings as errors. Source rereview closed that
finding with no remaining material blocker in the examined scope. Root
integration and the full regression gate remain separate requirements.

An earlier 22-assertion run passed but its
coverage gate failed because the initial runner preloaded the module before
measurement; that failure is retained, not described as a coverage pass. The
corrected final runner uses a lazy import overlay against actual root dependencies.
