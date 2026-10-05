# V0 source HTTP process boundary

The PUBLIC, EQUITY, MACRO and PRIORITY HTTPS adapters execute their single fixed
request in a disposable `spawn` worker. This closes the prior slow-DNS and
slow-header gap: a socket inactivity timeout alone can be prolonged by a server
that sends header bytes slowly. The parent starts its 20-second clock before
process creation and bounds the complete DNS, connect, TLS, request, header and
body sequence. It does not retry. Normal shutdown has a 0.2-second join allowance;
termination/reaping and response-reader cleanup each have a two-second bounded
allowance. A failure to reap is an explicit error, not a successful result.

This is a resource boundary, not HOST_ENFORCED protection or a security sandbox.
The worker applies native Windows Job or Linux rlimit controls: 256 MiB process
memory, five CPU seconds, and no core dumps on Linux. The Windows job also permits
only one active process and kills members when the job handle closes. Unsupported
platforms and failed native-limit setup fail closed. These settings affect the
disposable worker, never the parent application's or host's global limits.

`sources/process_http.py` uses a closed dispatcher. Callers cannot supply a
function, module name, script or callback. The worker reconstructs one of the
existing typed requests and rechecks its fixed provider host, exact permitted
path/query shape and header-only authentication rules. The wire primitive remains
private as `_send_once`; normal callers must use `send`. No redirect, proxy,
automatic retry, new provider endpoint or live broker capability was added.

Request envelopes are capped at 8,192 bytes. Credentials remain only in parent
and child memory and the anonymous local startup pipe. They are not command-line
arguments, files or diagnostics. Source errors are restricted to bounded symbolic
codes; unexpected exceptions become a generic network/process error. Provider
response and retry metadata remain bounded, and the existing connector checks
still reject reflected credentials before materialization.

The response is a length-prefixed JSON metadata block plus raw bytes, sent through
one anonymous one-way pipe. The parent uses `recv_bytes` with a maximum frame of
2,001,028 bytes and validates status, retry metadata and the 2,000,000-byte body
limit. It never deserializes a pickled response. A dedicated response reader lets
the parent enforce its deadline even if the child stalls partway through writing
a frame. Finally blocks close pipe ends, join or kill/reap the child, and join the
reader. No worker response is treated as research approval or historical timing
evidence; candidate status and pending/quarantined quality are unchanged.

## Tests and integration

`tests/test_v0_source_deadlines.py` launches actual subprocesses with known
module-level test fixtures. Those fixtures replace DNS, socket creation, TLS and
HTTP inside the spawned child before invoking the real worker. They never access
the network. Marker files demonstrate that the stalled DNS/header stage was
actually reached; tests assert a sanitized timeout and no surviving child.
Successful spawned requests, malformed/missing IPC, startup failure, strict
dispatch, frame bounds and native-limit setup/denial are separately exercised.
Native platform API doubles test failure branches without changing the test
parent's OS resource limits; the successful spawned cases apply real limits.

Existing mocked wire tests in `test_v0_sources.py`,
`test_v0_source_equities.py`, `test_v0_sources_macro.py`, and
`test_v0_sources_priority.py` now call `_send_once`. A spawned process correctly
does not inherit parent monkeypatches, so using their former `send` call would
invalidate those unit fixtures. The new tests exercise the public `send` boundary
separately. All existing DNS/TLS/authentication/status/byte-limit assertions remain.

On 2026-10-05 the five-file regression batch completed with 443 tests passing
under Python 3.14.7 and `-W error` in 38.79 seconds. Combined statement/branch
coverage for the five transport modules was 97.15%; the new process boundary
was 98.11%. Ruff check/format and strict mypy passed for the changed modules and
new test file. This is focused implementation evidence; independent review and
the parent repository's complete regression gate remain separate requirements.

Run the five test files together under the pinned Python environment. All test
temporary files, caches, dependency installations and evidence must remain on
Disk D. Use an explicit D-based `--basetemp` and D-based coverage/cache paths.
Parent integration owns the full regression gate, independent review, current
source-document timeout paragraphs, decision/status reconciliation and Git.
## Native application spawn correction

The standalone wire tests did not initially exercise the application's `-m`
entrypoint. A subsequent native application probe retained `NETWORK_FAILURE`.
An offline reproduction forced the exact `quant_hunter.web.main` spawn
preparation name and imported the production API/runtime in the child. Before
the native limit was established that graph consumed297,476,096 private bytes,
already above256MiB; real `ssl.create_default_context()` subsequently raised
`SSLError` under the limit. No DNS or network call was made in that diagnosis.

Application imports now occur inside `main()` after argument parsing. Spawn
initialization therefore imports only the lightweight entry module. The same
offline diagnostic then measured24,694,784 private bytes before the limit and
25,563,136 after successful real TLS context creation. The memory cap remains
256MiB. This fixes application-child initialization; it does not imply that an
external provider request succeeded.

`test_v0_native_source_spawn.py` uses that actual production module preparation,
establishes the real native limits and loads the actual system certificate store,
without DNS/socket/network calls. It failed against the original application
entrypoint and passed after the lazy-import correction. Together with the26
deadline tests,27 tests passed with warnings treated as errors; the final focused
regression, Ruff check/format and strict mypy also passed. The test asserts that
API/runtime imports are absent from the child and that no child remains after
completion. Parent integration and whole-application regression remain distinct.
