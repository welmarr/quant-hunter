# Budget Ledger

## Authority and Hard Limit

This is the canonical aggregate record for project spending, commitments, approvals, and remaining Month-1 headroom across every category—not only data. Total Month-1 cost must not exceed USD $400, including ChatGPT subscriptions, OpenAI API use, servers/infrastructure, market or economic data, and all other paid services. No agent may purchase, subscribe, start a charge-converting trial, or otherwise commit funds without explicit user approval.

DEC-0010 defines Month 1 as `[2026-09-04T00:00:00-04:00, 2026-10-04T00:00:00-04:00)` in `America/New_York`. Pre-existing fixed subscriptions materially used by Quant Hunter are allocated by actual invoiced cost, including tax, across overlapping service days; when service dates are unavailable, the full invoice or renewal charged in the window counts. Project API usage, currency conversion, taxes, setup and cancellation fees, usage exposure, and non-cancelable recurring obligations count under DEC-0010. Until all material baseline facts are entered, headroom is unknown and no purchase is allowed.

## Required Entry Schema

Every proposed or actual cost receives a permanent ID such as `COST-<uuidv7>` and records:

- category, provider, product, purpose, and linked research or infrastructure requirement;
- cost class and pricing date, currency, conversion basis, taxes/fees, Month-1 maximum, recurring amount, and cancellation terms;
- free/open-source alternatives and consequence of deferral;
- license, retention, redistribution, rate-limit, and lock-in constraints where applicable;
- status: `PROPOSED`, `APPROVED`, `COMMITTED`, `SPENT`, `REJECTED`, or `CANCELLED`;
- explicit approval reference and approver for any status beyond `PROPOSED`;
- committed and actual amounts, invoice/reference, start/end dates, and owner; and
- linked source, risk, and decision IDs.

Rejected and cancelled entries remain visible. Approval of one item does not approve later usage, renewal, overage, or a different service.

## Month-1 Summary

| Window | Cap | Recorded baseline | Approved/committed | Spent | Remaining headroom |
|---|---:|---:|---:|---:|---:|
| 2026-09-04 00:00 EDT (inclusive) to 2026-10-04 00:00 EDT (exclusive) | USD 400 | UNKNOWN | USD 10 | USD 10 | UNKNOWN |

The USD 10 approved/committed amount is the same purchase shown as spent, not an
additional USD 10 liability. It does not assert that existing subscriptions or
project API usage have zero cost. The owner must provide relevant invoice
amount/service dates and project-attributable API usage. For each item, the
ledger counts actual Month-1 spend when final, otherwise its approved or
committed maximum; any unknown material amount keeps headroom `UNKNOWN`.

## Entries

One owner-reported purchase is recorded below. Stage 1B Batches 1–4A use
free/open-source CPython, uv, Hatchling, Ruff, mypy, pytest, pytest-cov,
coverage.py, jsonschema, referencing, rfc3339-validator, and types-jsonschema at
USD 0 direct cost. Batch 3B adds the Apache-2.0 `rfc8785` 0.1.4 package at USD 0
and creates no service, subscription, or usage commitment. On 2026-09-05 the
repository was verified public and GitHub's
current documentation stated that standard GitHub-hosted runners are free for
public repositories; the workflow uses only standard Ubuntu/Windows runners,
no cache, and no artifact upload. Larger runners are prohibited, and visibility
or billing-policy changes require immediate reassessment. These zero-cost tools
do not resolve the unknown pre-existing subscription/API baseline, so headroom
remains `UNKNOWN`.

Batch 4A uses only the Python standard library and existing locked dependencies
for local immutable object and synthetic raw-capture foundations. Batch 4B.1 adds
Apache-2.0 PyArrow 25.0.1 at USD 0 direct cost for deterministic local Parquet
encoding. Batch 4B.2 uses the same locked dependencies for synthetic PIT
selection. This final review-fix implementation adds no service, data, storage,
subscription, usage commitment, or direct cost. The separate owner-reported
purchase already made for project capacity is recorded below.
Item 8A reuses the same locked local dependencies and prepaid capacity. Its
incremental direct project cost is USD 0; consumption of the recorded prepaid
credits is not counted again as separate spend.
The Item 8A timestamp-ordering review fix uses only the Python standard library
and adds USD 0 incremental direct cost.
Item 8B reuses the same locked dependencies, registry, canonicalization, and
immutable-object foundations. It adds no service, data, infrastructure,
subscription, or usage commitment and has USD 0 incremental direct cost.
Item 8C reuses those same local foundations for evaluation evidence, decisions,
immutable result-object verification, and deterministic rerun resolution. It
adds no dependency, service, data, infrastructure, subscription, usage
commitment, or incremental direct cost.

### COST-01a0751b-6555-73d9-961e-78c98ff8405b — OpenAI Codex credits

- **Category / provider / product:** implementation capacity / OpenAI / Codex credits.
- **Purpose:** reserve/additional Codex implementation capacity for Quant Hunter.
- **Cost class:** non-recurring prepaid purchase; recurrence and cancellation terms are not applicable based on the owner's report.
- **Purchase date / currency / Month-1 actual:** 2026-09-06 / USD / USD 10.
- **Status:** `SPENT`.
- **Approval:** explicitly approved and reported by the project owner in the current Stage 1B work.
- **Committed / actual amount:** USD 10 / USD 10, based on the owner's report.
- **Taxes and fees:** unknown; no additional amount is imputed.
- **Invoice, payment reference, and service period:** not provided.
- **Alternative / deferral consequence:** use only already available no-additional-cost capacity; implementation may proceed more slowly.
- **Owner / linked risks:** project owner / RISK-013 and RISK-021.

The USD 10 is an already-made project purchase recorded against the Month-1 cap.
The unresolved pre-existing subscription/API baseline keeps remaining headroom
`UNKNOWN`; this ledger does not claim that USD 390 is available.

Paid-source proposals must also satisfy `DATA_SOURCE_REGISTRY.md`; infrastructure, API, subscription, and tooling proposals use this ledger even when no data source is involved.

## Review

Recalculate totals before every approval, commitment, usage increase, renewal, and stage gate. Record expected cost before recommending a paid dependency. Prefer open-source libraries and authoritative free datasets, avoid GPU infrastructure unless quantitatively justified, and use expensive AI models selectively.
