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
| Cost Constraint (421–433) | `AGENTS.md`, `PROJECT_CHARTER.md`, `BUDGET_LEDGER.md`, `DATA_SOURCE_REGISTRY.md`, `RISK_REGISTER.md` | USD $400 Month-1 aggregate total; approval evidence and headroom; no purchase without approval; open/free preference; GPU and paid-dependency restraint; selective expensive AI. |
| What To Do Now and Success (434–475) | `ROADMAP.md`, `DECISIONS.md` | Original ordered foundation work, tests/linters, completion-report fields, no strategy-first coding, no execution-only success, Stage 1 definition. |
| Pattern Lab mandate and A–O (476–791) | `PATTERN_DISCOVERY.md` | First-class lab; all method families and submethods; outcome registry fields; multivariate example; nearest-state distribution; strict validation; deferred ML and simple baselines. |
| Pattern Lab Principle (792–816) | `PATTERN_DISCOVERY.md`, `MODEL_REGISTRY.md` | Statistical objective, role as independent evidence family, and no duplicate votes for closely related pattern variants. |

## Independent-Reviewer Correction Mapping

| ID | Explicit requirement | Governing destination |
|---|---|---|
| QH-REV-001 | Algorithm Discovery Program as an operational stage | `ROADMAP.md` Stage 2A; canonical candidate records in `MODEL_REGISTRY.md` |
| QH-REV-002 | Prioritized hierarchy of authoritative algorithm sources | `ROADMAP.md` Stage 2A |
| QH-REV-003 | Registration-first canonical algorithm implementation with tests, point-in-time data, costs, IDs, variants, assumptions, and reproducible configuration | `ROADMAP.md` Stage 2B; `RESEARCH_METHODOLOGY.md`; `VALIDATION_STANDARD.md` |
| QH-REV-004 | Honest reproduction outcomes, including unavailable-data failure | `ROADMAP.md` Stage 2B; `MODEL_REGISTRY.md`; `RESEARCH_METHODOLOGY.md`; `VALIDATION_STANDARD.md` |
| QH-REV-005 | Pattern Lab as an explicit post-Stage-1 implementation/research sub-stage | `ROADMAP.md` Stage 2D; normative detail in `PATTERN_DISCOVERY.md` |
| QH-REV-006 | Pattern Lab exit gate covering operational families, IDs, search volume, false-discovery controls, sealed OOS, reproducibility, stability, and rejection ability | `ROADMAP.md` Stage 2D; enforcement in `PATTERN_DISCOVERY.md` and `VALIDATION_STANDARD.md` |
| QH-REV-007 | Long-term expansion toward approximately 200+ serious models, not a quota | `ROADMAP.md` Stage 3A; `PROJECT_CHARTER.md`; `MODEL_REGISTRY.md` |
| QH-REV-008 | Evidence-family governance and protection against duplicate ensemble votes | `ROADMAP.md` Stage 3B; canonical taxonomy and lineage in `MODEL_REGISTRY.md` |
| QH-REV-009 | Automated research pipeline from candidate proposal through scientific decision, with compatible statuses and no automatic promotion | `ROADMAP.md` Stage 3C; canonical statuses in `MODEL_REGISTRY.md` and `EXPERIMENT_LEDGER.md` |
| QH-REV-010 | Permanent research backlog, including deferred, missing-data, expensive-data, infrastructure-bound, anomalous, and legitimately revisitable rejected ideas | `ROADMAP.md` Stage 3D |
| QH-REV-011 | AI contributors to a hypothesis cannot access its sealed OOS data before freeze; sealed-result changes require a new experiment and genuinely untouched evidence where possible | `ROADMAP.md` Stage 4; `RESEARCH_METHODOLOGY.md`; `VALIDATION_STANDARD.md` |

## Added Non-Negotiable Clarifications

The user's 20 explicit operating rules are retained verbatim in substance as the numbered rules in `AGENTS.md`. Detailed enforcement lives in the referenced domain documents, including immutable raw data, point-in-time macro vintages, reproducibility, permanent IDs, inaccessible sealed OOS data until freeze, methodology decisions, realistic execution, research/production isolation, secrets, AI limits, simple baselines, failure retention, and the approval-gated USD $400 budget.

## Project Continuity and Regression Governance

| Requirement | Governing home |
|---|---|
| A future conversation, Codex session, or agent can recover the current reviewed resume point from repository evidence. | `AGENTS.md`; `PROJECT_STATUS.md`; DEC-0029 |
| Every material batch preserves prior reviewed scientific, security, reproducibility, identity, and authority invariants through the full regression and review sequence. | `AGENTS.md`; `REGRESSION_GUARD.md`; DEC-0029 |
| Current status may be updated without rewriting historical decisions, risks, development evidence, or Git history. | `PROJECT_STATUS.md`; `DECISIONS.md`; `RISK_REGISTER.md`; DEC-0029 |
| Material deferred work is tracked operationally without replacing durable repository authority or bypassing a current-batch blocker. | `ISSUE_GOVERNANCE.md`; `.github/ISSUE_TEMPLATE/material-deferred-work.yml`; DEC-0034 |
| Issue closure requires stated acceptance criteria, regression evidence, and reconciliation of affected durable authorities. | `ISSUE_GOVERNANCE.md`; `AGENTS.md`; DEC-0034 |

## Stage 1B Item 10A Sealed-OOS Software Mapping

| Requirement | Governing and implementation evidence |
|---|---|
| Exact FROZEN authorization remains subordinate to Item 8 lifecycle authority. | DEC-0031; `EXPERIMENT_LEDGER.md`; `experiments/lifecycle.py`; `test_sealed_release.py` |
| Every supported exposure write crosses the release-service authority boundary; no public raw ledger writer can manufacture a release or incident. | DEC-0033; `isolation/ledger.py`; `isolation/release.py`; API-surface, raw-mapping, nonexistent-experiment, and supported-writer tests |
| Release binds the experiment, sole FROZEN revision and manifest, complete dataset-ID set, exact sealed interval, reproducibility identities, time, and immutable released artifact. | `sealed-release-event.schema.json`; `isolation/release.py`; authorization and cross-binding hostile tests |
| Event identity is RFC 8785 JCS plus SHA-256 over the complete body excluding only `event_digest`, including the prior digest. | DEC-0031; `isolation/ledger.py`; digest permutation and mutation tests |
| Exposure is global to every dataset and exact half-open interval component across experiments; authorized release requires a wholly pristine footprint, while later incidents remain appendable. | DEC-0032; `sealed-release-event.schema.json`; `sealed-exposure-incident.schema.json`; cross-experiment, overlap, adjacency, multi-dataset, ledger CAS, chain, retention, and truncation tests |
| Release terminates every new search while allowing only a fixed zero-new-search evaluation through Item 8. | DEC-0031; `experiments/lifecycle.py`; lifecycle integration tests |
| Retained release evidence remains verifiable through later Item 8 states against the exact historical FROZEN authority and retained event digest. | DEC-0032; `experiments/lifecycle.py`; FROZEN/RUNNING/EVALUATED/DECIDED verification tests |
| Item 10A evidence is synthetic only and cannot claim the separately gated host boundary. | `ARCHITECTURE.md`; `REGRESSION_GUARD.md` REG-F01–REG-F03; synthetic-mode and poisoned-filesystem tests |

Item 10A is `COMPLETE / INDEPENDENT REVIEW PASSED / MERGED / POST-MERGE CI
GREEN` at main `20851f262041cda1fe26844032f298b2a1531ffd`.

## Stage 1B Item 10B Windows Host Mapping

| Requirement | Governing and implementation evidence |
|---|---|
| `HOST_ENFORCED` cannot be claimed by a raw mapping or Item 10A service. | DEC-0035; `windows_host.py`; typed-construction, platform, schema, and service rejection tests |
| Host evidence binds only complete successful checks, sanitized location fingerprints, explicit limitations, and its canonical digest. | `windows-host-boundary-evidence.schema.json`; `WindowsHostBoundaryVerifier`; tamper, wrong-profile, failed-check, secret-text, and append-only tests |
| Host release retains exact Item 8 FROZEN, dataset/partition, code/config/environment, artifact, ledger CAS, history, overlap, and search-termination authority. | `WindowsHostReleaseService`; conditional release-event schema; Item 10A/10B hostile tests |
| Host setup is bounded to an already protected fixed NTFS volume and performs no BitLocker mutation. | `item10b_preflight.ps1`; inert `item10b_setup.ps1`; static safety tests; DEC-0035 |
| Dedicated identity, allow-list DACL, audit/SACL, index, sync, backup, denial, release, and account-disable assertions require live evidence. | Windows host scripts; REG-F03; RISK-017; sanitized 2026-09-11 blocker evidence |

Item 10B is `IMPLEMENTED TOOLING / HOST EVIDENCE BLOCKED`. The code and tests do
not establish real Windows isolation or complete Roadmap Item 10.

## Coverage Maintenance Rule

A requirement may be clarified or made stricter, but not silently weakened or deleted. Any methodological or statistical change requires `DECISIONS.md`; any move requires this table to be updated; any unresolved conflict applies the stricter scientific, safety, reproducibility, and spending constraint.

## Initial Stage 0 Refactor Audit

On 2026-09-04, the reorganized hierarchy was compared with the full source specification available during the refactor. Core and Pattern Lab audits found no missing or weakened substantive requirement after reconciliation. Automated checks confirmed all 16 Markdown files, all 15 README links, documentation-only scope, clean trailing whitespace, and 81 representative content checkpoints spanning the operating rules, registries, methods, metrics, data timing, execution assumptions, Pattern A–O, identifiers, budget, and stage boundaries.

The independent-review correction passed 88 roadmap content checks plus all 11 QH-REV traceability checks. Cross-document references resolved, the governing status vocabularies remained compatible, no requirement was weakened, and the repository remained documentation-only. Stage 0 may therefore return to `COMPLETE`; this does not authorize Stage 1.
