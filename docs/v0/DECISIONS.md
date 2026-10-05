# V0 decisions

## V0-D01 — Branch and authority reconciliation (2026-10-05)

The owner's direct request makes `version-0` the working and integration branch.
It takes precedence over the attachment's example `build/quant-hunter-v0` name.
`work-before-v0` was created from the clean current checkout and remotely verified
at `7346cf4f79ca5897777c0118f8cf4c2292be929e`. No uncommitted relevant files existed.
The original local main (`c350c26`) and remote main (`e0ba326`) remain untouched.
No existing branch was overwritten and no ignored local material was discarded.

The owner explicitly authorizes continuous V0 implementation, local simulation,
and paper-only software. This supersedes the old one-batch stop convention for
this mission only. It does not certify Stage 1 completion, authorize host/security
mutations, spending, external messages, real-money execution or sealed data access.
Independent review and actual host evidence keep their original meaning.

## V0-D02 — Native first, bounded storage

Keep the existing checkout at `D:\quant-hunter`; do not move it. Use its ignored
`.local/v0` directory for application runtime/data/artifacts and `.tools` for
dependency caches, interpreters and test temporaries. Separate secrets from
shareable runtime exports. On 2026-10-05 C: had 7.0 GiB free; D: had 205.7 GiB
free, with 15.7 GiB RAM and eight logical CPUs. Avoid heavy Docker builds until
the actual VHD location and adequate storage have been verified. Docker's reported
Linux `/var/lib/docker` is not proof of the Windows VHD location.

## V0-D03 — First executable slice and scientific authority

Start with deterministic synthetic forex/equity examples and an accounting
oracle, using Decimal, explicit costs, delayed fills and immutable evidence.
Reuse the existing Item 8 registry/lifecycle; operational job state is never
scientific authority. No research workflow receives a sealed source path.
The UI must state SYNTHETIC and empirically unvalidated. Confirmatory evaluation
and live broker authority remain blocked. Unsupported market/cost behavior is
rejected, never silently approximated. Every later capability gets its actual
status in REQUIREMENTS and FEATURE_MATRIX before any completion claim.

## V0-D04 — Native application and numerical conventions

FastAPI and Uvicorn provide the loopback API and server, with locked dependencies.
SQLite holds only users, hashed sessions and operational jobs. Item 8 alone owns
scientific lifecycle and attempt accounting. A single process lease and worker
avoid concurrent application writers. Interrupted jobs never silently replay;
retained Item 8 evidence is finalized or marked failed, preserving each attempt.
Actual source bytes (base64 in an immutable snapshot), lockfile, environment,
configuration, synthetic dataset and result hashes permit precise attribution.

The initial deterministic long/flat rule compares closed marks to the registered
lookback, then executes at the next strictly later opening quote (buy ask, sell
bid). Decimal precision is 38 with ROUND_HALF_EVEN. Full fills, cash funding,
unadjusted synthetic marks, no exchange calendar, and no corporate actions are
explicit limitations. Every commission, adverse slippage and ACT/365 financing
assumption is supplied. Spread is already reflected in execution cash, and is
not subtracted twice. Final positions are marked, never fictitiously liquidated.

Manual/AI parameter choices receive new experiments in the same evidence family.
All demonstration results are INCONCLUSIVE; there is no automated scientific
decision or promotion. These tests prove software arithmetic, not market returns.

Primary software references consulted 2026-10-05:
[FastAPI](https://fastapi.tiangolo.com/tutorial/) and
[TypeScript](https://www.typescriptlang.org/docs/handbook/intro.html).
No paid service or additional account was used. Hosted CI's existing public,
standard-runner profile now also runs on version-0 pushes.

## V0-D05 — Declared uploads and bounded public diagnostics

CSV/Parquet imports accept a closed bar schema and explicit instrument, license
and availability declarations. Raw bytes and normalized Parquet have separate
immutable identities, using existing raw-capture/derived-data authorities.
Corrections allocate new IDs. Reads replay normalization and verify the complete
graph. Structural PASS does not approve source rights, vintage timing, market
coverage or research validity. Upload evidence `HISTORICAL` means uploader-
declared historical origin, not verified historical availability. It is never
silently relabeled SYNTHETIC or admitted to the current synthetic simulator.

The initial limits are 2,000,000 raw bytes, 16,000,000 decoded bytes and 100,000
rows. Native Parquet timestamp/fixed numeric schemas and bounded page metadata
are checked before Arrow decoding. No arbitrary paths, URLs, archives or schema
inference enter the importer. Pagination bounds default dataset verification.

BLS v1 monthly series and ECB daily reference FX use fixed public HTTPS endpoints,
public-IP pinning with hostname TLS, bounded responses and no automatic retries.
Each explicit small probe creates a reviewed CANDIDATE source before acquisition,
retains exact bytes and creates a PENDING dataset. Latest revisions retain UNKNOWN
publication/revision times and remain ineligible for historical PIT use. ECB
reference rates remain indicative. Credentials are not needed by these clients.
The application serializes admission, limits BLS to 25 probes per rolling day,
limits each user to one probe per minute, and retains failed/interrupted work.

All imports/probes combined are capped at 1,000 operations in this initial
profile, preserving the 2 GB cumulative raw-acquisition budget. Runtime admission
checks the 30 GB storage cap and reserves at least 20 GiB or 15% of the volume.
The native profile aggregates its `.local` runtimes, results and backup copies;
an explicitly configured root outside `.local` receives its own bounded check
and requires owner accounting of other external roots.
Existing material is not deleted when a limit is reached. These native profile
limits remain visible limitations; larger research must receive a separately
reviewed bounded configuration. No paid source, live trading or scientific
promotion is introduced. SEC/Alpaca clients are subsequent isolated work, not
already integrated by the BLS/ECB checkpoint.

## V0-D06 — Private offline backup format

Backup and restore use a versioned, checksum-manifest ZIP_STORED format, with
bounded central-directory metadata, files, sizes and total bytes. The runtime
must be stopped and its OS lease acquired before backup. Restore accepts a new
destination only and holds its lease while publishing. Every member is verified
before and during extraction; SQLite integrity is checked before removing an
incomplete-restore marker. An incomplete runtime cannot launch.

The archive is PRIVATE: it contains local accounts/password hashes and source
data governed by their original rights. It must never enter Git or a shared
export. Master keys/credential stores are excluded and require a separate owner
procedure when introduced. An archive proves preservation of bytes and database
integrity, not scientific validity or authorization to share those bytes. No
existing archive, destination, user data or cache is overwritten or purged.

## V0-D07 — Canonical market identity and private source configuration

DEC-0040 governs the integrated INSTRUMENT kind, canonical revisions, market
metadata knowledge/effective times, pinned XNYS/named-FX calendars, explicit
session aggregation and authenticated private configuration. Ticker correction
does not change permanent identity; asset class and base/quote currency changes
require a new identity. Owner-declared metadata do not establish historical PIT
facts. Shared local reference metadata are distinct from private datasets/jobs.

Source configuration is a complete encrypted atomic slot outside checkout and
runtime. Saving, rotating and locally revoking keys makes no network request.
The source test is an explicit owner action with existing quotas, rights and
no-incremental-charge declarations. Only fixed read-only hosts are available;
no live-account purpose or broker order endpoint is admitted. Windows DPAPI and
Linux private files have explicit same-user/administrator/rollback limitations.
Credentials use separate owner recovery, never an ordinary runtime archive.
No scientific or host gate, purchase, or original research authority changes.
