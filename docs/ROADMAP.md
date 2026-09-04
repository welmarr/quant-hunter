# Roadmap

## Stage Gates

Progression is evidence-gated, not calendar-gated. No later stage is authorized by completing an earlier document. Strategy implementation, paper trading, shadow validation, and controlled capital each require separate scope and approval.

## Stage 0 — Documentation Architecture

Deliver and cross-link the persistent operating rules, charter, architecture, research methodology, validation standard, data specifications, registries, pattern-lab requirements, decisions, risks, roadmap, and traceability map. Audit the hierarchy against the former master specification.

**Exit gate:** all requirements have a governing home, all required documents exist, links and required rule phrases pass review, and no strategy or Stage 1 code has been introduced.

## Stage 1 — Reproducible Research Foundation

Do not implement the proposed 200 strategies. After explicit authorization, perform the following ordered work:

1. Reinspect the repository and governing documents.
2. Refine `AGENTS.md` only if an invariant or navigation rule changed.
3. Review and approve the full Stage 1 architecture; resolve open decisions.
4. Maintain the project documentation structure and traceability.
5. Select the supported Python version and package manager, then create the minimal project scaffold.
6. Create machine-readable experiment, model, pattern, and data-registry schemas with permanent IDs.
7. Research and populate legitimate data sources; do not purchase anything without explicit approval.
8. Create validation interfaces, sealed-holdout controls, test scaffolding, and reproducibility checks.
9. Prioritize implementation work and update this roadmap.
10. Record every unresolved assumption in `DECISIONS.md` rather than silently guessing.

After planning, implement only the foundational infrastructure necessary for Stage 1. Use tests, and run every documented test and linter. Do not claim success simply because code executes.

**Exit gate:** Quant Hunter is a reproducible quantitative-research laboratory in which it is difficult to accidentally fool ourselves. Evidence must demonstrate immutable/provenanced data, frozen experiments, inaccessible sealed OOS data, realistic backtest interfaces, multiple-testing accounting, registries, deterministic reruns, tests, and security/deployment separation.

## Stage 2 — Canonical Research Reproduction

Reproduce or transparently approximate the ten foundational areas in `RESEARCH_METHODOLOGY.md` before proprietary combinations. Use permanent IDs, registered protocols, point-in-time data, cost-aware backtests, and full validation. State proprietary-data limitations; failed reproductions remain results.

Classical Pattern Discovery methods may enter research only after the Stage 1 controls exist. Pattern candidates are research objects, not trade signals.

## Stage 3 — Distinct Strategy Families

Develop only evidence-supported families from `MODEL_REGISTRY.md`. Compare every complex model to simple baselines, measure regime/cost sensitivity, and reject duplicate parameter variants as independent evidence. The target breadth is long-term and never a quota that weakens standards.

## Stage 4 — Ensembles, Meta-Models, and AI Research

Study dependence-aware ensembles and meta-models. AI may assist literature review, hypotheses, critique, anomaly detection, and candidate code; all variants count toward multiple testing. Pattern and related-family models do not receive duplicate votes. AI has no execution authority.

## Stage 5 — Paper Trading

Introduce paper-only adapters and credentials behind a separate boundary and authorization. Compare simulated assumptions with observed spreads, slippage, latency, fills, data arrival, and operational failure modes.

## Stage 6 — Shadow Validation

Run forward, non-capital validation without strategy-development access to future observations. Require stability, reproducibility, calibration, and risk review before any further proposal.

## Stage 7 — Controlled Capital

This stage is only eventual. It requires explicit approval, independent risk and security review, production isolation, monitoring, kill controls, and a new decision record. Nothing in the current repository authorizes live trading.

## Required Completion Report for Implementation Milestones

Report the repository tree, architecture summary, files created, commands and tests executed, test results, major design decisions, data sources identified, major risks, unimplemented scope, and recommended next milestone. Report failures and limitations with the same prominence as successes.
