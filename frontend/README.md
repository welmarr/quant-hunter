# Quant Hunter workstation frontend

This TypeScript application is served by the local Python API. The browser has
no production JavaScript dependencies, CDN requests, external fonts, analytics,
or stored authentication credentials. The server sets the HttpOnly session
cookie; the session CSRF value stays in memory.

From this directory:

```text
npm ci --ignore-scripts --no-audit --no-fund
npm run typecheck
npm run build
```

The project-local npm configuration keeps its cache on
`D:/quant-hunter/.tools/npm-cache`. TypeScript 5.9.3 is pinned with its integrity
hash in `package-lock.json`. `app.ts` compiles to the committed
`src/quant_hunter/web/static/app.js`. Rebuild the JavaScript whenever its source
changes. `index.html` and `styles.css` live beside that generated asset.

The Phase A views use the actual session, fixture, job, result, user and project
endpoints. No seeded performance or placeholder completed jobs are displayed.
Active jobs refresh once per second; a terminal state stops polling. Network
failures pause polling and expose a manual retry. Operational job status is
explicitly distinct from the existing governed experiment lifecycle. Independent
runs are not combined into an invented portfolio.

Accessibility includes labelled form fields, keyboard-visible focus, a skip
link, current navigation state, accessible error/status messages and a text data
table for the SVG chart. The sidebar becomes an explicit mobile menu; wide
accounting tables scroll inside labelled, keyboard-accessible regions.

The integration owner runs the full Python regression gate and real-browser
workflow checks with the running API. TypeScript success alone is not browser,
scientific, security, or complete V0 acceptance evidence.

`npm run test:browser` exercises a running synthetic test installation at
`http://127.0.0.1:8765` using installed Chrome or Edge. It never downloads a
browser. Start a separate empty runtime before its first run. The test creates
a randomly credentialed owner, then researcher/reader accounts and actual
registered fixture backtests. Existing accounts and experiments are retained.
Never point it at an installation containing an unrelated owner account.

Environment overrides are `QH_E2E_URL`, `QH_E2E_BROWSER`, `QH_E2E_OUTPUT`,
`QH_E2E_PRIVATE`, and `QH_E2E_REFERENCE`. Screenshots and their JSON evidence
manifest default to `.local/v0-proof` beside the project. Test-only account
credentials are stored separately in `.local/v0-browser-private` for reruns;
this private directory must not be shared or committed. Browser temporaries
remain in `.tools/browser-temp`. Screenshot evidence records actual viewport,
URL, capture time and SHA-256; the reference must honestly identify an
uncommitted snapshot when applicable.

Set `QH_E2E_PHASE_B=1` to include the actual source catalogue, CSV import,
immutable correction, bounded dataset pagination, and data access checks.
`QH_E2E_PARQUET` may identify a local synthetic Parquet fixture for the same
upload workflow. These tests do not query external providers by default.
Only set `QH_E2E_LIVE_PROBE=1` when one bounded public ECB retrieval has been
explicitly authorized; its actual response and limitations are retained in
the proof manifest. `QH_E2E_EXPECTED_STATIC` may identify the committed
JavaScript asset in a separate clean checkout for an exact served-byte check.

The Data view loads 25 owned dataset versions per page. Imports and account
changes reset to the first page. Historical availability and licensing remain
uploader declarations, and imports do not enable historical backtesting.
