# Run the first V0 slice

This is an in-progress V0 application. Backtests currently use synthetic data;
imports and bounded public-source diagnostics have separate provenance. No
historical returns or real-money capability are claimed.

From Windows CMD in `D:\quant-hunter`:

```bat
pwsh.exe -NoLogo -NoProfile -File scripts\windows\start_v0.ps1
```

Open http://127.0.0.1:8765 and create your local owner account. Use a new password
of at least 12 characters. There are no default credentials. Create researcher or
reader accounts in Settings. Each user sees only their own jobs and results.

Select a synthetic equity or FX fixture and run the fixed causal momentum
calculation. Lookback 1 produces the explicit accounting positive control.
Costs are assumptions you supply, not measured market costs. The four-bar fixture
does not validate a strategy, exchange calendar, liquidity or future performance.
The experiment is frozen through Item 8 before calculation and remains
INCONCLUSIVE. Sealed data is never read or released.

Ctrl+C stops the server. On restart, queued jobs continue; abandoned running
attempts are retained and reconciled, never automatically recomputed. Retry means
a new registered experiment. A filesystem lease prevents two server processes
from owning one runtime. Native SQLite stores only operational accounts/sessions/
jobs; governed JSON registry revisions and immutable objects remain scientific
authority. All application data lives in ignored `.local/v0` on D:.

To use a distinct demo/test instance:

```bat
pwsh.exe -NoLogo -NoProfile -File scripts\windows\start_v0.ps1 -Runtime D:\quant-hunter\.local\v0-demo -Port 8766
```

Dependencies use the existing pinned uv and CPython toolchain. The locked
FastAPI/Uvicorn additions provide the local API and server. Static frontend assets
are shipped; Node is needed only when changing the TypeScript frontend. The server
binds exclusively to 127.0.0.1. Public deployment and TLS termination are not part
of this local slice. Cookies are HttpOnly/SameSite Strict on loopback HTTP; this
profile is unsuitable for public network exposure.

Source/configuration/environment/dataset/result bytes are bound by immutable
digests. An actual source snapshot is retained for runs made before a development
commit, with the Git parent labeled separately.

Sources now lists all 22 mission catalogue entries with their actual implementation
status. BLS and ECB have explicit bounded test buttons; a successful connection
does not approve a dataset or establish point-in-time history. No background
network probe runs merely because you open the page. Other connectors remain
unconfigured/unimplemented until their respective work is verified.

Data accepts CSV or Parquet files up to 2,000,000 bytes. The required columns are
`open_at,close_at,available_at,open_bid,open_ask,close`; optional columns are
`high,low,volume`. CSV timestamps need explicit offsets or Z. Parquet timestamps
must be native and timezone-aware, with fixed numeric/decimal price/volume types.
Nested, binary and string column schemas are refused. Every row must be valid;
no missing price is silently filled and duplicate/contradictory bars are refused.
The page offers a clearly synthetic sample. Declare the source, license and
instrument; a declaration is not verified permission or historical availability.
Imports preserve exact raw bytes and new immutable normalized versions. They are
not yet connected to the synthetic-only backtest. Read details and limits in
`SOURCES.md` and the requirement matrix.

Private backup and verified restoration commands are in `OPERATIONS.md`.

PatternLab, canonical research studies, paper brokers, notifications, portfolio/
ensemble workflows and later acceptance requirements remain tracked in
REQUIREMENTS.md. Do not infer completion from navigation entries.
