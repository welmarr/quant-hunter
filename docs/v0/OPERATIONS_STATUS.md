# Private operational observations

`OperationsAccess(state, runtime, worker_status=...)` and
`install_operations_routes(app, authenticated, access)` expose one read-only
`GET /api/operations/status`. The host retains session, origin and route policy;
the adapter rechecks the exact current user name and role in its own read-only
SQLite transaction. It opens the existing database with `mode=ro` and
`query_only`, a 250 ms lock timeout and a cooperative two-second SQLite progress
budget. It creates no database, job, experiment, receipt, quota or recovery action.

The response contains `observed_at`, `database`, `private`, `global`, `worker`,
`limits`, `storage`, and an explicit read-only, non-scientific authority label.
`private` counts only the current account's operational state. `global` is null
for researchers/readers; owners receive aggregate counts without another user's
IDs, names, payloads, errors, configuration, data or scientific results. The
existing `resource_counts` helper remains the authority for global counts. One
RUNNING worker with its owned RUNNING child consumes one slot. Orphan children
remain counted. Optional missing modules are absent from component summaries,
not presented as installed empty services. Unknown retained status text becomes
`OTHER`, never a channel for arbitrary diagnostic text.

Each count object contains `components` (fixed table names with status/count
maps), `active_slots`, `reserved_slots`, `reader_slots`,
`linked_worker_children` and `orphaned_active_children`. These are operational
reservations, not scientific attempts. The configured limits are two active
slots and eight total reservations. Observing them never grants admission.

The trusted host callback must be a cheap nonblocking in-memory observation and
returns `WorkerStatus(state, generation=None, started_at=None)`. State is RUNNING,
STOPPED, RESTARTING or UNKNOWN. A supplied generation is a bounded nonnegative
integer; it is not inferred from jobs or represented as a measured restart count.
The optional start time is timezone-aware. Invalid/failed callbacks produce
UNKNOWN with a fixed sanitized reason, with no exception text or traceback.
This module cannot start, stop, replay, repair or claim work.

Only owners receive storage observations. The configured Windows runtime must
be on D. Returned records include no filesystem paths. The budget scope matches
the native data service's nearest `.local` ancestor, falling back to the runtime
when absent. The scanner reads metadata only, rejects encountered symlinks,
reparse points and special files, and stops at 100,000 entries or a cooperative
two-second budget checked between metadata operations. It does **not** interrupt
a blocked `disk_usage`, `lstat` or `scandir` system call and is not a process or
host-enforced deadline. Concurrent writes can race the sample.

Storage has a 30-second cache, a five-second failed-refresh backoff and a
nonblocking scan lock. Its `freshness` is LIVE_SAMPLE, CACHED, STALE or UNAVAILABLE.
Every sample retains its own observation time and age. Failed, expired or busy
refreshes report current `status=UNKNOWN`, even if the prior sample said OK.
The retained sample remains visibly historical. The reserve is the larger of
20 GiB and 15% of volume capacity; the displayed reference headroom is 64 MB and
the shared runtime cap is 30 GB. Individual operations, including Pattern corpus
work, can require stricter reserves. These measurements do not authorize work.

Database failure returns sanitized HTTP503; no cached count or authorization is
served. Revoked or changed users receive403. Authentication failures preserve
the host's response. Successful status responses carry `Cache-Control: no-store`.

## Executed fault evidence

The isolated suite passed46 tests in72.74seconds with99.20% combined statement
and branch coverage. Ruff and strict mypy on both modules passed. The known
pinned Starlette TestClient deprecation warning was filtered by its exact warning
class; all other warnings were errors. An earlier unfiltered collection failed
on that known warning and is retained separately.

The harness uses real AppState SQLite. It executes current-role/name revocation,
missing and exclusively locked databases, bounded query interruption, same-job
concurrent claims, linked parent/child collapse, retained interrupted recovery,
worker-generation changes without replay, optional paper/publication/read
reservations, sanitized malformed states, cache failure/backoff, storage entry
and cooperative time limits, redirection/special-file metadata rejection and
actual file-size totals. It asserts no source payload, secret or private path in
responses and no database change from ordinary observation. Redirection metadata
faults are injected; this is not live host-isolation evidence.

Evidence: `D:/quant-hunter/.tools/ui-operations-final.xml` and
`D:/quant-hunter/.tools/ui-operations.coverage`. The exact tested package is
`D:/quant-hunter/.tools/operations-reference`, copied from the current integrated
support baseline plus these two owned modules. Independent review and the
integration owner's full repository/browser/remote checks remain separate gates.
