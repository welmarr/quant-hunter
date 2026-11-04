# Run the native V0 laboratory on D:

V0 delivery is still in progress. This guide describes the integrated native
workflows; [RESUME.md](RESUME.md) and [TEST_REPORT.md](TEST_REPORT.md) state which
exact source and browser checks have passed. Synthetic backtests and paper
sessions prove software behavior, not historical or future profitability.

## Start and sign in

Prerequisites: the checked-out `version-0` repository on D:, the documented pinned
uv/CPython toolchain, and a browser. See `../DEVELOPMENT.md` for toolchain setup and
quality commands. No Docker, API key, broker account, AI service or purchase is
required for the local synthetic workflows. Node is needed only to edit/build
the TypeScript frontend; compiled assets are shipped in the package.

From Windows CMD in `D:\quant-hunter`:

```bat
pwsh.exe -NoLogo -NoProfile -File scripts\windows\start_v0.ps1
```

The launcher installs/synchronizes the locked environment, puts managed Python,
uv caches and temporary files under D:, resolves the actual repository revision,
and binds only `http://127.0.0.1:8765`. If dependency synchronization or revision
resolution fails, it stops with an error. Read the failure; do not bypass the lock.

Open that address and create the local owner account with a new password of at
least12 characters. There are no default credentials. Settings lets the owner
create researcher/reader accounts and inspect audited account maintenance.
Research results remain private to their originating account. Keep browser-test
accounts separate from your actual owner account.

For a distinct instance, choose an unused port and new D: runtime:

```bat
pwsh.exe -NoLogo -NoProfile -File scripts\windows\start_v0.ps1 -Runtime D:\quant-hunter\.local\v0-demo -Port 8766
```

The private vault defaults outside the repository/runtime under
`D:\QuantHunterPrivate\<runtime-identity>`. An explicit `-PrivateRoot` must be a
distinct absolute private location. Credentials/master keys never go in chat,
source, URLs or ordinary backups. Windows DPAPI uses the application's Windows
identity. See [CREDENTIALS.md](CREDENTIALS.md) before any owner key recovery.
Loopback HttpOnly/SameSite cookies are not a public-network deployment profile.

## First visible backtest and research workflow

1. Open Backtests. Select the labelled synthetic equity, cash ETF or FX fixture,
   choose the bounded causal lookback and explicit cost assumptions, and submit.
2. Wait for the actual task state to finish. Inspect cash, orders/fills, result
   provenance and the permanent experiment identity. The fixture is a controlled
   software example; it does not establish exchange liquidity or a winning method.
3. In Studies, choose a canonical method and its baseline/positive/null/sensitivity
   scenario. Every evaluated variant receives an Item8 experiment before work.
   Failed and inconclusive studies remain visible. Inspect train/test cutoffs,
   numerical outputs, actual model identities and the reference-method limits.
4. Compare existing completed studies in Comparison. Comparison reads retained
   results; it does not create a new evaluation or make unlike horizons comparable.

Quality, PatternLab and Validation use explicit owned immutable input selections.
Start with the clearly synthetic sample in Data quality, declare its mapping and
calendar, inspect the quality report, and create the chronological selection.
Build an owned corpus, choose a closed query and train range, inspect actual
bars, freeze the preparation, then enqueue it. Parameter changes invalidate the
previous preview/preparation. Fifteen method families have concrete classical
calculations; a displayed match is not a probability of profit. Inspect actual
occurrences, raw/normalized overlays, negative cases, costs, counted exposure and
exact/approximate status. Validation freezes its chronological protocol before
its job; an unavailable sealed holdout is never opened as a shortcut.

The publication library supports recorded references and permitted local files,
actual bounded extraction, reading status, method/equation mappings and private
experiment links. Bibliographic metadata does not mean full text was read.
Research can be performed without an AI provider.

## Sources, imports and historical inspection

Sources lists22 catalogue entries and their actual capabilities and external
requirements. Public BLS, Federal Reserve G17 and ECB probes make fixed small
queries only when deliberately requested. Source status/quality remain
CANDIDATE/PENDING; a successful response does not approve historical timing or
rights. Private authenticated sources require owner configuration and an explicit
test. Saving configuration makes no request. Read the displayed source-specific
limits and [SOURCES.md](SOURCES.md); conditional providers are not silently skipped.

Data imports preserve exact CSV/Parquet bytes and immutable versions. The ordinary
upload bound is2,000,000bytes, with explicit timezone, units, source and licensing
metadata. Use the UI's required column mapping and no missing-price substitution.
Corrections create new identities instead of replacing earlier source bytes.
Data quality supports actual bounded aggregation, including explicitly anchored
5h/session rules and incomplete-bar rejection. Instrument reference history is
shared metadata; an owner's local record is not a verified historical vintage.

Historical inspection displays a bounded literal chart/table only after quality
admission. Unknown availability, missing revision timing or contradictions can
block inspection/research. Diagnostic provider previews and owner declarations
do not turn an imported dataset into an approved causal backtest. Costs, missing
history and unavailable rights remain visible. No ten-year free-data entitlement
is assumed by the scale benchmark.

## Local paper execution and protection

Create a configured LOCAL_PAPER or REPLAY session from the synthetic native fixture,
inspect its limits, then explicitly activate. The durable engine processes actual
causal decisions, risk admission, next-opening fills, partial fills, cash/positions,
reconciliation and reports. Its clock is the fixture replay time, not a live market.
Execution shows current state, errors, risk controls and retained unknown outcomes.

Pause, cancel orders or use the persistent local-paper halt when appropriate.
The global halt protects all local sessions; clearing it does not resume them or
erase existing positions/losses. Resume requires current ownership, exact revision,
provenance and reconciliation. Portfolio shows one session's verified retained
cash, bid exposure and native observations; it never sums independently funded
runs into fictitious wealth. Acknowledged broker protocol messages are not fills.

The fixed Alpaca paper/OANDA practice adapters have offline contract workflows.
Their real account access and credentials remain external requirements. No broker
order, real-money key or external account is needed for local testing. LIVE_DISABLED
is not a switch that an experiment, paper or LLM can turn on.

Notifications has an operational private local inbox. Optional Telegram requires
owner configuration and an explicit sending/test action; it is disabled without
that configuration. No real token or message was used for the default proofs.

## Stop, recover and troubleshoot

Use Ctrl+C in the launcher terminal and wait for the worker/server to stop. A
filesystem lease prevents concurrent ownership of one runtime. Queued work can
continue after restart; interrupted/unknown attempts are retained and reconciled,
not silently replayed. A deliberate retry is a separately counted experiment.
Never delete a runtime or clear its database to make a failed task disappear.

[OPERATIONS.md](OPERATIONS.md) gives exact private backup/restore commands. Stop the
runtime first, create a new archive, and restore into a different nonexistent
path. The UI's Backup panel prepares commands; it does not pretend an archive was
created or verified. Test restored accounts, immutable evidence and paper state.
Restore the private vault only through its separate owner procedure.

- Busy503 means the bounded shared resource is occupied. Retry the read after its
  delay; do not repeatedly submit the experiment. A403 means ownership/role refusal.
- A stale revision409 requires refresh and deliberate review of the new state.
- An unavailable worker or invalid source report blocks new work; inspect
  Operations and the retained task error. Do not bypass a failed integrity check.
- Low disk admission stops work before publication. Inspect storage usage; never
  delete raw evidence or saturate the real disk to test the refusal path.
- For an occupied port, choose another unused port and distinct instance; do not
  terminate an unidentified process or remove an active lease.

Private backups and raw datasets are not shareable reports. See
[SHARING.md](SHARING.md) for sanitized review artifacts and [EXTENSIONS.md](EXTENSIONS.md)
for concrete connector, method, cost, pattern and optional AI extension contracts.
