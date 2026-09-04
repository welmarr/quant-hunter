# Budget Ledger

## Authority and Hard Limit

This is the canonical aggregate record for project spending, commitments, approvals, and remaining Month-1 headroom across every category—not only data. Total Month-1 cost must not exceed USD $400, including ChatGPT subscriptions, OpenAI API use, servers/infrastructure, market or economic data, and all other paid services. No agent may purchase, subscribe, start a charge-converting trial, or otherwise commit funds without explicit user approval.

The exact Month-1 calendar window and treatment of pre-existing subscriptions are open decisions in `DECISIONS.md`. Until resolved and the baseline is entered here, treat available headroom as unknown and do not authorize a purchase. Currency conversion, taxes, setup fees, usage exposure, and recurring charges count toward the cap.

## Required Entry Schema

Every proposed or actual cost receives a permanent ID such as `COST-0001` and records:

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
| Awaiting `DECISIONS.md` resolution | USD 400 | UNKNOWN | USD 0 | USD 0 | UNKNOWN |

`USD 0` above means no new project commitment or spend is recorded in this repository; it does not assert that existing subscriptions have zero cost. Resolve the baseline before evaluating any purchase.

## Entries

No purchases or paid commitments are recorded. Paid-source proposals must also satisfy `DATA_SOURCE_REGISTRY.md`; infrastructure, API, subscription, and tooling proposals use this ledger even when no data source is involved.

## Review

Recalculate totals before every approval, commitment, usage increase, renewal, and stage gate. Record expected cost before recommending a paid dependency. Prefer open-source libraries and authoritative free datasets, avoid GPU infrastructure unless quantitatively justified, and use expensive AI models selectively.
