# V0 feature matrix

V0 remains IN_PROGRESS. Software verification is distinct from historical or
scientific validation. The first executable slice uses SYNTHETIC data only.
Source-linked acceptance requirements remain in REQUIREMENTS.md.

| Capability | Software status | Evidence and remaining scope |
|---|---|---|
| Native launch and first backtest | IN_PROGRESS | Running native application and verified UI oracle; clean-clone launch pending |
| Owner/researcher/reader authentication | PASS | Local role boundaries verified by API and real browser; additional account administration remains future work |
| CSV/Parquet immutable import | IN_PROGRESS | Implementation underway in isolated agent checkout; not yet exposed |
| 22-source catalogue and priority connectors | IN_PROGRESS | Catalogue and first public clients underway; not yet exposed |
| Instrument registry and PIT quality | NOT_STARTED | Foundation PIT controls retained; full application integration pending |
| Paper library and ten sourced CRP implementations | NOT_STARTED | No empirical reproductions claimed |
| Fifteen PatternLab families | NOT_STARTED | Complete mission scope retained |
| Bounded multi-scale pattern search and benchmarks | NOT_STARTED | Complete mission scope retained |
| Equity/FX accounting and costs | IN_PROGRESS | Synthetic Decimal momentum, next-bar bid/ask, commission, slippage and financing; broader market conventions pending |
| Governed experiments and chronological validation | IN_PROGRESS | Item 8 freeze/attempt/evidence integration verified; full validation workflows pending |
| Portfolio and ensemble/meta-model baseline | IN_PROGRESS | Individual actual run portfolio view only; no aggregate/ensemble implementation |
| Persistent local paper execution and risk | NOT_STARTED | Live trading disabled; continuous paper engine remains required |
| Paper broker adapters and contract tests | NOT_STARTED | External credentials absent; offline client implementation remains required |
| Local notifications and optional Telegram | NOT_STARTED | No external messages sent |
| Worker restart/cancellation/recovery | IN_PROGRESS | Single leased worker, queued cancellation and interrupted-attempt preservation verified; complete job operations pending |
| Security and failure tests | IN_PROGRESS | Auth/CSRF/origin/ownership/worker/immutable-evidence checks executed; broader threat and fault suite pending |
| Backup/restore and clean-clone proof | NOT_STARTED | Git backup verified; runtime restoration not yet implemented |
| Responsive UI, browser evidence and status | IN_PROGRESS | Six functional views verified at desktop/mobile/tablet; later modules pending |

Executed commands, failures, corrective reviews and artifact locations are in
TEST_REPORT.md. No host gate or stage transition is claimed.
