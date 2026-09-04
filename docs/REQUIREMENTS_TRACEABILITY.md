# Requirements Traceability

## Purpose

This map records where the former 816-line Quant Hunter master specification now lives. It is a coverage index, not a substitute for the governing documents. Update it whenever a requirement moves or changes.

## Master-Specification Mapping

| Former section | Governing destination | Preserved content |
|---|---|---|
| Opening mandate and cautions (former lines 1–19) | `PROJECT_CHARTER.md`, `AGENTS.md` | Multi-role agent mandate; platform purpose; 75% aspiration as a question; no manufacture/target fitting; evidence priorities; failure retention; no early live trading, live credentials, or self-promotion. |
| Project Philosophy (20–82) | `PROJECT_CHARTER.md`, `MODEL_REGISTRY.md` | Bottom-up progression; AI boundary; distinct-family 200-model aspiration; complete foundational-family catalog and expansion rule. |
| First Milestone (84–89) | `PROJECT_CHARTER.md`, `ROADMAP.md` | Research foundation before strategies; scientifically defensible infrastructure. |
| Repository Architecture (90–118) | `ARCHITECTURE.md`, `DECISIONS.md` | Every required module/capability; clean interfaces; modern Python decision; package management; proportionate Docker and no premature distribution. |
| Persistent Documentation (119–138) | `AGENTS.md`, `README.md`, all `docs/` files | All named persistent documents plus the rule that integrity and reproducibility outrank impressive backtests. |
| Experiment Registry (139–170) | `EXPERIMENT_LEDGER.md` | Permanent ID; full minimum metadata; variant accounting; sealed interval; failures/rejections remain. |
| Anti-Overfitting Architecture (171–196) | `VALIDATION_STANDARD.md`, `EXPERIMENT_LEDGER.md` | Complete method list, chronological design, multiple testing, stability/degradation/regime analysis, and no alpha claim from headline metrics. |
| Data Architecture (197–264) | `DATA_ARCHITECTURE.md` | All market, macro, positioning/risk, cross-asset, and alternative-data fields; immutable layers; four times; vintage/revision protection and authoritative real-time datasets. |
| Data-Source Registry (265–300) | `DATA_SOURCE_REGISTRY.md` | Every provider field, executable/indicative status, licensing, tiers, authoritative-source preference, Stage 1 recommendation, and no-purchase rule. |
| Canonical Reproduction Program (301–333) | `RESEARCH_METHODOLOGY.md` | All ten research areas; complete per-study dossier; honest proprietary-data limitations. |
| Backtesting Standards (334–355) | `VALIDATION_STANDARD.md` | Bid/ask, costs, financing, slippage, latency, orders/fills, sessions, gaps, closures, missing data, rollover, leakage/survivorship, configuration reproducibility. |
| Metrics (356–390) | `VALIDATION_STANDARD.md` | The complete standard-report metric inventory, calibration, confidence, regime and cost sensitivity. |
| AI Boundary (391–410) | `AGENTS.md`, `PROJECT_CHARTER.md`, `RESEARCH_METHODOLOGY.md` | Allowed research assistance; no LLM execution; equal validation; every AI variant counted. |
| Security (411–420) | `AGENTS.md`, `ARCHITECTURE.md` | No secrets; sanitized `.env.example`; credentials excluded from history; paper credentials deferred. |
| Cost Constraint (421–433) | `AGENTS.md`, `PROJECT_CHARTER.md`, `DATA_SOURCE_REGISTRY.md`, `RISK_REGISTER.md` | USD $400 Month-1 total; no purchase without approval; open/free preference; GPU and paid-dependency restraint; selective expensive AI. |
| What To Do Now and Success (434–475) | `ROADMAP.md`, `DECISIONS.md` | Original ordered foundation work, tests/linters, completion-report fields, no strategy-first coding, no execution-only success, Stage 1 definition. |
| Pattern Lab mandate and A–O (476–791) | `PATTERN_DISCOVERY.md` | First-class lab; all method families and submethods; outcome registry fields; multivariate example; nearest-state distribution; strict validation; deferred ML and simple baselines. |
| Pattern Lab Principle (792–816) | `PATTERN_DISCOVERY.md`, `MODEL_REGISTRY.md` | Statistical objective, role as independent evidence family, and no duplicate votes for closely related pattern variants. |

## Added Non-Negotiable Clarifications

The user's 20 explicit operating rules are retained verbatim in substance as the numbered rules in `AGENTS.md`. Detailed enforcement lives in the referenced domain documents, including immutable raw data, point-in-time macro vintages, reproducibility, permanent IDs, inaccessible sealed OOS data until freeze, methodology decisions, realistic execution, research/production isolation, secrets, AI limits, simple baselines, failure retention, and the approval-gated USD $400 budget.

## Coverage Maintenance Rule

A requirement may be clarified or made stricter, but not silently weakened or deleted. Any methodological or statistical change requires `DECISIONS.md`; any move requires this table to be updated; any unresolved conflict applies the stricter scientific, safety, reproducibility, and spending constraint.
