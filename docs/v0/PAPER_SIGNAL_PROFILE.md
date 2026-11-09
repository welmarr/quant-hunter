# Opt-in synthetic paper signal profile

`QH_PAPER_SIGNAL_V1` is an explicitly chosen new-session profile. It freezes a
declared target horizon and an intent expiry before the existing Item8
registration and before any decision, admission or fill. It supplies no new
lifecycle, model, confidence, empirical validation, external order permission or
current market signal. The deterministic bid-versus-lagged-bid rule fits no model.

This is the implementation proposal for DEC-0049. Parent review, independent
methodological review and the integrated full regression remain required before
acceptance. The existing scientific gates, sealed-data restrictions and human
approval boundaries remain unchanged.

## Explicit configuration and causal contract

New `configuration.signal_generation` must have exactly:

```json
{"profile":"QH_PAPER_SIGNAL_V1","horizon_bars":4,"ttl_seconds":60}
```

`horizon_bars` is an integer from 1 through 100. `ttl_seconds` is an integer from
1 through 3600, no greater than `horizon_bars * 60`. Booleans, null, unknown
profiles and extra fields fail. There is no automatic upgrade. The unchanged
legacy defaults remain at `/api/paper/configuration` under `defaults`; separate
`opt_in_signal_defaults` make the choice explicit. Both LOCAL_PAPER and REPLAY
still use the synthetic fixture's simulated bar-close clock, not wall time or a
live venue clock.

The owner-selected fields and full expanded `signal_generation_contract` are in
the frozen canonical configuration. The permanent STRAT parameter digest and EXP
refer to these bytes. The strategy definition identifies this variant, while the
same existing research family retains the attempt exposure. Changing a parameter
requires a new session/EXP; failed and inconclusive attempts remain retained.

For decision time `t`, the target horizon ends at `t + horizon_bars * 60 seconds`
and expiry is `t + ttl_seconds`. The horizon is always labelled NOT_EVALUATED:
this profile does not inspect a future target, calculate a success rate, force
liquidation at the horizon or manufacture a return beyond the fixture. The
boolean `horizon_within_fixture` states only whether the declared target time is
inside the frozen fixture interval. It is not outcome availability or a forecast
quality assertion. Signal confidence is null and external_actionable is false.

## Actual local execution behavior

At each next bar open, an existing reservation's originating retained signal is
resolved before matching. `opened >= expires_at` is expired: the actual native
Cancel REQUEST/CONFIRM commands remove the remainder before any Match. Equality
is deliberately excluded. A missing originating intent fails closed.

At every later bar close, the previous unfilled remainder is cancelled before
the new decision and admission. If it has reached expiry the command IDs carry
`.signalexpiry`; otherwise they carry `.signalsuperseded`. Those are retained
native command annotations, not a new mutable event authority. The established
engine determines cancellation outcome, cash release, reconciliation and any
fault behavior. A profile-driven cancellation must actually remove the target
reservation and OPEN order before processing may continue. A rejected or
unconfirmed cancellation fails the workflow before any Match or replacement
admission; the residual reservation remains visible in the retained native state.
The profile does not implement a second accounting calculation.

Cancellation affects only the unfilled remainder. Executed partial fills,
commissions, cash and residual position exposure stay in the actual book.
Expired intent does not mean the portfolio is flat or free of risk. A later
decision may submit a fresh locally risk-checked order from the resulting book.

Expiry is enforced at the simulator's existing open/close processing points.
There is no intervening tick stream, autonomous wall-clock expiry worker or
promise of cancellation at a real-world instant. There is no fill opportunity
between those simulated points. No fill at or after expiry is permitted by this
workflow. Supersession changes only the opted-in profile; its extra cancellations
and new admissions can change costs and outcomes and are part of the frozen
variant, not a cosmetic display change.

## Immutable evidence and compatibility

New reports retain the expanded contract. Each decision contains `generation`
with the contract digest, clock, horizon, expiry, target-evaluation status and
explicit nonactionability. Repeated fields are recomputed from the frozen
configuration and corresponding bar close during reads/execution. Correctly
rehashed reports with changed or missing generation fields fail verification.

Legacy configuration has no `signal_generation`; legacy frozen input, fixture
and report branches do not acquire any new fields. Its horizon/expiry remain
UNKNOWN in Signals. Exact original code/environment archives still verify
historical production; current execution requires the current matching source
and environment. Old records are never rerun automatically or regenerated from
today's defaults. Historical inspection does not compare their producer with
today's revision. The source dependency list is unchanged.

Public helpers `signal_generation_contract(config)` and
`paper_signal_fields(frozen_config, decision_time)` are pure derivations for the
verified Signals adapter. They do not authorize a source or instruction. The
adapter must first verify actual ownership and the complete retained paper graph
under the shared read reservation; legacy UNKNOWN and prospective replay-only
status remain separate. Root owns the optional creation controls, runtime wiring
and browser verification.

## Required evidence

Synthetic tests cover legacy byte oracles from the preserved pre-profile
producer; registration before the first native command; exact expiry equality;
partial fills followed by expiry or supersession; persistent native replay;
closed authenticated route payloads; unevaluated horizons beyond the fixture;
coherently rehashed generation claims; historical producer inspection;
process interruption during each cancellation stage; and actual rejected native
cancellation without an expired fill.
Test outcomes, independent review and exact file hashes belong in the final
handoff. No historical performance or live execution claim follows from these
software tests.

## Scoped verification evidence

The corrected source passed all 30 new profile cases and 73 existing paper
workflow cases (103 tests, 407.00 seconds). That initial scoped
coverage command failed its 90% threshold at 86.68%, because existing halt and
mutation safety paths were not included; its failure remains retained and is
not represented as a passed gate. The same exact source then passed all 55 existing halt and mutation-read tests
(209.25 seconds). Appending that meaningful coverage produced 92.05% combined
statement/branch coverage across paper_access and paper_routes: 158 tests passed
in the two final test runs, with no exclusions or threshold reduction. The
second run did not import routes and emitted the expected coverage warning;
the route coverage is retained from the preceding 103-case run. Integrated
full regression remains a separate root responsibility.

Independent review read the complete narrow source and methodological proposal
and executed six selected tests against the exact corrected source: legacy
byte preservation, exclusive expiry, partial fill/supersession, and rejected
native cancellation (six passed, 60.08 seconds). This closes the reviewed
software boundary only. Root owns final integration, the optional creation UI,
Signals reader compatibility, browser verification and hosted regression.
