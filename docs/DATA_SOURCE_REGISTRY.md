# Data Source Registry

## Purpose

The Data Source Registry is the authoritative inventory of every external dataset considered or used by Quant Hunter. A source must be registered and reviewed before ingestion. Registration documents what the data represents, when it was knowable, whether it is lawful and reproducible to use, and whether its quality is adequate for the intended research.

Research current, legitimate sources and prefer authoritative primary providers when possible. A convenient aggregator is not automatically equivalent to the originating authority or an executable market feed.

## Permanent records

Assign each source a typed UUIDv7 identifier such as `SOURCE-01990f30-7f5e-7b34-9b21-3d74c513c841` under DEC-0009. Never recycle identifiers. Preserve superseded, rejected, unavailable, and failed-source evaluations with their status and reason; do not silently delete them. Material source changes create a new append-only revision with the prior revision digest and require impact review for affected datasets and experiments. Machine authority is the schema-validated JCS chain at `registries/sources/<id>/vNNNNNN.json`; Markdown and generated indexes are views.

## Required fields

Every registry entry must record at least:

| Field | Requirement |
|---|---|
| Source ID | Permanent unique identifier |
| Provider | Legal or authoritative provider name |
| URL/documentation reference | Direct source and relevant API/schema/licensing documentation |
| Asset/data type | Domain, series/feed type, instruments, and coverage |
| Granularity | Tick, event, bar, daily, monthly, release-level, or other native frequency |
| Historical depth | Earliest coverage, gaps, and whether history varies by instrument/series |
| Real-time availability | Live, delayed, end-of-day, periodic release, historical only, or unknown |
| Latency | Known publication/feed latency, measurement method, and uncertainty |
| Cost | Current quoted fixed, usage, storage, egress, and setup costs, with currency and review date |
| Free tier | Limits, retention, eligibility, and material exclusions |
| API restrictions | Authentication, permitted uses, concurrency, pagination, query, retention, and automation limits |
| Redistribution restrictions | Whether raw or derived data may be shared, cached, published, or included in artifacts |
| Licensing constraints | License, attribution, user/seat, geography, research/commercial, and derived-work conditions |
| Rate limits | Published quotas and observed throttling, if known |
| Reliability | Availability history or evidence, correction practice, support, version stability, and known incidents |
| Historical revisions/vintages | Whether initial releases and historical vintages exist, how they are queried, and any gaps |
| Price nature | Executable bid/ask, venue quote/trade, broker-specific quote, composite, indicative, midpoint, or not applicable |

Also record the registry-record version, status, owner/reviewer, initial and latest review dates, access method, source-native identifiers, time-zone/time-semantics notes, expected Stage 1 usage, provenance/checksum support, quality limitations, replacement sources, and linked decision/risk entries where applicable. Unknown facts must be marked `UNKNOWN`, not guessed.

## Cost classification

Use exactly one primary class and state the classification basis:

| Class | Meaning |
|---|---|
| `FREE` | No purchase required for the proposed use; document attribution, quota, and license limits |
| `LOW-COST` | Modest paid access potentially compatible with the project budget, but still requires approval |
| `PREMIUM` | Material subscription or usage cost requiring a demonstrated research need and explicit approval |
| `INSTITUTIONAL` | Enterprise, exchange, terminal, negotiated, or otherwise impractical access for the initial retail-scale laboratory |

Promotional trials and academic-only access do not make a source `FREE` for unrestricted project use. Record the post-trial cost and eligibility conditions.

## Selection standard

Evaluate sources in this order:

1. Point-in-time correctness: clear event/publication/revision semantics and historical vintages where the research requires them.
2. Authority and fidelity: prefer central banks, statistical agencies, regulators, exchanges, or original publishers over secondary copies.
3. Price meaning: distinguish executable bid/ask data from indicative, composite, delayed, or midpoint observations.
4. Provenance and reproducibility: stable identifiers, documented schemas, retrievable vintages, checksums or equivalent controls, and lawful retention.
5. Coverage and fitness: required instruments, fields, granularity, historical depth, sessions, and survivorship/roll metadata.
6. Reliability: documented corrections, operational stability, support, and feasible rate limits.
7. Legal use: compatible licensing, caching, sharing, and redistribution terms.
8. Total cost: access plus setup, compute, storage, egress, maintenance, and future switching costs.

Conflicts must be explicit. For example, authoritative macro data may be preferred even if a secondary API is easier, while execution research may require broker- or venue-specific quotes rather than a clean indicative history.

## Stage 1 source policy

- Recommend the minimum authoritative `FREE` sources needed to establish ingestion, provenance, vintage, quality, and reproducibility workflows.
- Research real-time/vintage macro datasets such as ALFRED/FRED and equivalent authoritative sources; verify rather than assume their revision coverage and time semantics.
- Document all four applicable timestamps: event time, publication time, ingestion time, and revision time.
- Defer alternative data until evidence justifies its value, licensing is clear, and its incremental cost is approved.
- Do not introduce institutional feeds, paid order books, or GPU-dependent data services merely for anticipated future scale.
- A source without sufficient historical vintages must not be used for point-in-time macro research as if its latest values were historically available.
- A source containing indicative prices must not be represented as executable bid/ask history.

## Purchasing and budget control

No agent may purchase, subscribe to, start a paid trial that can convert to a charge, or commit the project to any service. Every paid recommendation must first document:

- the specific research requirement and why approved free sources are insufficient;
- cost class and complete expected Month-1 and ongoing costs;
- license, redistribution, retention, rate-limit, and cancellation constraints;
- lower-cost alternatives and the consequence of deferral; and
- the decision and explicit human approval reference.

Total Month-1 spending across ChatGPT subscription, OpenAI API use, servers, market/economic data, and every other paid service must remain at or below USD 400. No purchase may be made without explicit approval, even when it would fit the remaining budget. Expected cost must be documented before recommending any paid dependency.

## Registry review workflow

1. Create a candidate record with source documentation and all unknowns visible.
2. Review legitimacy, authority, license, access restrictions, and cost.
3. Test a non-sensitive sample for schema, timestamps, coverage, revision behavior, and price meaning.
4. Record quality findings, limitations, and reproducibility evidence.
5. Assign `CANDIDATE`, `APPROVED`, `REJECTED`, `DEPRECATED`, or `UNAVAILABLE` status with reason and reviewer.
6. Link approved ingestions and dataset manifests to the exact registry-record version.
7. Re-review when terms, schema, API, pricing, provider ownership, or observed reliability changes.

Rejected and deprecated sources remain in the registry so later agents do not repeat hidden failures or unknowingly change the information set.
