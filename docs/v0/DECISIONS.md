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
