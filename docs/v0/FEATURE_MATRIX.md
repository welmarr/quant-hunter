# V0 feature matrix

V0 remains IN_PROGRESS. Software verification is distinct from historical or
scientific validation. Backtests use SYNTHETIC data; public acquisitions and
uploader declarations retain separate modes and unresolved timing/rights.
Source-linked acceptance requirements remain in REQUIREMENTS.md.

| Capability | Software status | Evidence and remaining scope |
|---|---|---|
| Native launch and first backtest | PASS | Documented clean-clone launcher and 20 real-browser checks passed at 9b74dd6; new checkpoint builds and restores independently |
| Owner/researcher/reader authentication | PASS | Local role boundaries verified by API and real browser; additional account administration remains future work |
| CSV/Parquet immutable import | IN_PROGRESS | Private UI/API imports, exact raw/normalized identities, corrections and hostile parsing verified; larger corpus, mappings and research integration remain required |
| 22-source catalogue and priority connectors | IN_PROGRESS | All 22 entries visible; bounded BLS/ECB public probes verified; encrypted SEC/Alpaca configuration and concrete read-only clients integrated with actual provider access unverified; macro/other clients remain isolated |
| Instrument registry and PIT quality | IN_PROGRESS | Canonical UUIDv7 identity/history/CAS, owner writes, shared reference reads, XNYS/named-FX sessions and bounded causal aggregation integrated; imported-data aggregation workflow and historical metadata verification remain |
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
| Security and failure tests | IN_PROGRESS | Auth/ownership, XSS, SSRF, bounded Parquet/ZIP, disk, interruption, private encryption/rotation/recovery and account-switch checks; broader V0 threat/fault suite remains |
| Backup/restore and clean-clone proof | PASS | Private archive restored to distinct runtime: 265 identical files/equal database counts and 32 restored-browser assertions; scope/limits in OPERATIONS.md |
| Responsive UI, browser evidence and status | IN_PROGRESS | Sources/Data and private Settings verified; Markets browser proof in TEST_REPORT.md; later mission modules remain |

PASS applies only to the stated bounded capability and evidence. It does not
complete the mission or certify a host/stage/scientific gate. See TEST_REPORT.md
for executed commands, failures, corrections and retained artifact locations.
