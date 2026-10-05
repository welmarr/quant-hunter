# Hosted compatibility capacity correction

On 2026-10-05, exact checkpoint
`0541337699a246762fdaae1b83819b9ecbc18301` ran Quality #56,
[run 37303138649](https://github.com/welmarr/quant-hunter/actions/runs/37303138649).
Ubuntu passed 2,288 tests, one platform skip and one existing warning in 296.36s,
with 92.91% combined statement/branch coverage. Formatting, lint and strict
typing passed.

Windows started at 11:28:21 UTC and was cancelled at 11:38:28 UTC by the existing
ten-minute job bound. The retained log reports 1,596 passed, one platform skip,
one existing warning and no failing test before interruption at 571.59s of test
execution. This is incomplete Windows evidence, not a compatibility pass. The
corrected full local Windows regression had already passed all 2,288 tests in
998.05s, including coverage instrumentation.

The Windows job limit is now thirty minutes. Every test, action/dependency pin,
locked environment, runner and Ubuntu coverage threshold remains in force.
Ubuntu retains its ten-minute limit. A separate agent reviewed the configuration
change and found no exclusions or weakening of checks; its review is a software
cross-check, not professional certification. Exact follow-up CI must pass before
claiming hosted Windows compatibility for the next saved checkpoint.
