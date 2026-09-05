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
| 2026-09-04 00:00 EDT (inclusive) to 2026-10-04 00:00 EDT (exclusive) | USD 400 | UNKNOWN | USD 0 | USD 0 | UNKNOWN |

`USD 0` above means no new project commitment or spend is recorded in this repository; it does not assert that existing subscriptions or project API usage have zero cost. The owner must provide relevant invoice amount/service dates and project-attributable API usage. For each item, the ledger counts actual Month-1 spend when final, otherwise its approved or committed maximum; any unknown material amount keeps headroom `UNKNOWN`.

## Entries

No purchases or paid commitments are recorded. Stage 1B Batch 1 uses free/open-source CPython, uv, Hatchling, Ruff, mypy, pytest, pytest-cov, and coverage.py at USD 0 direct cost. On 2026-09-05 the repository was verified public and GitHub's current documentation stated that standard GitHub-hosted runners are free for public repositories; the Batch 1 workflow uses only standard Ubuntu/Windows runners, no cache, and no artifact upload. Larger runners are prohibited, and visibility or billing-policy changes require immediate reassessment. These zero-cost tools do not resolve the unknown pre-existing subscription/API baseline, so headroom remains `UNKNOWN`.

Paid-source proposals must also satisfy `DATA_SOURCE_REGISTRY.md`; infrastructure, API, subscription, and tooling proposals use this ledger even when no data source is involved.

## Review

Recalculate totals before every approval, commitment, usage increase, renewal, and stage gate. Record expected cost before recommending a paid dependency. Prefer open-source libraries and authoritative free datasets, avoid GPU infrastructure unless quantitatively justified, and use expensive AI models selectively.
