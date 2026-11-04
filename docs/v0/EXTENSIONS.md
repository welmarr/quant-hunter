# Extending V0 without changing its authority boundaries

This is a development guide for future authorized software slices. The V0 build
request does not authorize live trading, paid services or later-stage research.
Use the locked Python toolchain and current `docs/DEVELOPMENT.md` quality commands;
run the full regression suite and independent invariant review for material work.

## Add a source or file profile

Start from `sources/catalog.py` and the bounded clients and parser contracts in
`sources/`. Declare the exact market, asset type, query, units, quote direction,
coverage, entitlement and source capability. Keep credentials in the scoped
private connection service, not query parameters, logs or fixtures. Use fixed
allowlisted endpoints and reviewed bounded transport; redirects, private network
addresses, unknown formats and oversized responses must fail closed.

Parse retained raw bytes through an explicit versioned schema. Use the existing
raw capture, registry and diagnostic materializer rather than a second dataset
registry. Preserve retrieval time separately from event/publication/availability
and vintage. Unknown availability stays unknown. A correction creates a new
SOURCE/DATASET version. Public availability does not prove redistribution rights.
Tests should use synthetic or authorized bounded bytes, numerical examples and
hostile inputs. A fake-server protocol test proves the client contract only.

Wire private ownership and shared resource admission through `web/data_access.py`
and the existing routes. Respect two active operations/eight reservations,
operation identity, explicit cancellation and unknown-outcome recovery. Verify
that list summaries do not silently replay unbounded raw datasets. Add a real
UI/API path and prove that another account cannot inspect the private result.

## Add a method or representation

Canonical numerical studies live under `research_methods/`; PatternLab's executable
methods, corpus, search and product contracts live under `patterns/`. Declare
input columns, training cutoffs, timing, units, parameter bounds and resources.
Create permanent model/pattern identities before evaluation. Register every
parameter, manual/AI variant and failed trial through the existing Item8 lifecycle.
The web job store records ownership and scheduling; it is not scientific authority.

Provide independently calculated small-input oracles, a positive control, a null
control and a perturbation with a declared expected effect. Test changes to future
observations, availability, costs, currency orientation and alignment boundaries.
Keep fitting on train data and preserve sealed holdout restrictions. Bind source,
configuration, environment, seeds and exact outputs. Do not substitute a constant
score, empty wrapper or always-rejecting method for an executable implementation.

For a representation, state which source columns it uses and whether it affects
search, family diagnostics, outcomes or all three. Preserve raw prices for costs
and outcome calculations; changing a displayed normalization cannot silently
change economic assumptions. Bounded candidate retrieval must retain its measured
exact/approximate status and checkpoint binding.

## Add an execution adapter

The reviewed native `simulation/paper_engine.py` owns durable simulated economic
state. `simulation/crypto_execution.py` supplies an executable offline crypto test
plugin and explicit capability protocol. Use the existing paper-broker clients
and durable operation journal for fixed contract tests. Unsupported order types,
venues, settlement, currencies, funding and replacement behavior are explicit
rejections, not silent approximations.

An acknowledgement is not a fill. Preserve exact client identifiers and the
reconciliation-before-resubmission rule after an ambiguous timeout. Keep paper
and live credentials/URLs/accounts separate; LIVE_DISABLED remains a hard boundary.
Test partial fills, duplicate/disordered events, fill-after-cancel, crash recovery,
atomic risk limits and persistent kill switches. Protective actions must remain
possible under saturation without creating an uncounted compute slot. The local
simulator must work without credentials; no real broker order is a contract test.

## Extend costs or optional AI assistance

Cost changes belong in the explicit accounting/simulation contracts and frozen
experiment configuration. Preserve Decimal precision, tick/lot rounding, currency
units and event ordering. Add an independent cashflow oracle, then hold fills fixed
when testing a pure fee perturbation. A second experiment is needed when changed
costs also alter risk admission or fills; do not describe those runs as identical
trade paths. Corporate-action, financing, futures-roll or perpetual-funding rules
need explicit capabilities and unsupported-case rejection. Reconcile methodology
changes in DECISIONS.md and keep earlier experiment versions readable.

V0 research and publication workflows operate without an AI provider. Optional AI
assistance is not an authority to fit, evaluate, promote, trade or alter risk
limits. A future provider integration needs an explicit owner configuration,
private credential scope, fixed transport policy, spending approval and a bounded
quota/usage ledger before any paid request. The project-wide Month1 limit remains
USD400 and does not itself authorize spending. Preserve prompts, model/version,
inputs, costs and suggested variants with privacy/rights checks; every evaluated
suggestion counts in the same multiple-testing ledger as human work. Imported
papers or model responses are untrusted data, never executable agent instructions.
No arbitrary model confidence score becomes a calibrated win probability. Add
negative tests for fabricated citations, changed equations, secret leakage,
unavailable credentials and quota failure; retain a complete manual/no-AI path.
This is an extension contract, not a claim that an external AI provider was tested.

## Finish the slice

Update the capability catalogue, requirements/evidence matrix, affected decisions,
risks, invariant references and current status together. Preserve failed evidence.
Run actual owned UI/API flows, current full tests/coverage, formatting, strict
mypy, frontend typecheck/build and required reproducibility/restore checks. Obtain
independent review and exact-commit CI after a normal branch push. Do not mark
external entitlement, empirical validity or host isolation passed because local
software checks pass. Add no purchases or external sends without user authority.
