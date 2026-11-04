# Permanent model identities for mathematical Studies and validation

This application bridge uses the existing governed `MODEL` registry kind and
research-object schema. It is identity and provenance plumbing around the
reviewed mathematical functions. It neither changes their equations nor grants
scientific approval. Every recipe and fit record is `PROPOSED`; successful
synthetic computation remains `INCONCLUSIVE` under Item8.

## Allocation and immutable graph

`ModelIdentityBridge` receives the existing `AppState` and `LabService`. The
actual persisted, owned, RUNNING job and its exact request must match before
registration. One recipe MOD and the fixed list of fresh fit MODs are allocated
before `LabService.begin_run`. FIT records have the recipe as their parent.
Each record binds the job/owner, exact immutable configuration and actual input
bytes, code revision, environment (including the retained source archive when
provided), method definition and real input DATASET/SOURCE references when those
already exist. Failed and unused IDs remain permanent; no retry reuses a fit ID.

The Studies input exists before Lab allocates its synthetic DATASET. Therefore
its MOD `data_requirements` arrays are deliberately empty, and its parameters
bind the actual immutable input object. No fake dataset is allocated just to
fill a field. Validation instead binds its actual selected DATASET and canonical
source union, plus the exact original submission manifest containing the
snapshot, temporal plan and controls.

The Lab input is explicitly labelled `SOFTWARE_MODEL_INPUT_MANIFEST;
ACTUAL_INPUT_IN_REFERENCED_IMMUTABLE_OBJECT`. Its frozen configuration and bytes
contain the exact recipe/FIT receipts and actual input digest. It is not a bar
file. Actual fitted parameters are a separate immutable object linked to the
real EXP and exact registration. Null parameters mean no successful fit;
missing, substituted or contradictory artifacts fail inspection. The prefit
record's `experiment_ids` is empty because EXP does not yet exist. The later
immutable EXP configuration/input/output and owned job establish that link.

One definition-library FAM locates these proposed mathematical definitions. It
does not create new testing families or count attempts. Existing shared Studies
and validation EXP families, AI variant counts, failed attempts and Item8
lifecycle authority remain unchanged. Pure helper tests are software proof,
not research evaluations or historical evidence.

## Exact fit map

| Study | Recipe | Fresh fit identities and actual retained outputs |
|---|---|---|
| CRP-01,02,03,04,08,10 | Each execution | No reusable trained state: the recipe identifies the fixed causal signal/allocation method. Rolling diagnostics remain its output, not invented fitted models. |
| CRP-05 | Each execution | Cointegration regression: hedge/intercept, residual scale and diagnostic evidence; error-correction regression: actual ECM coefficients. ADF diagnostics are statistical tests, not separately deployable base models. |
| CRP-06 | Each execution | Training standardizer: means/scales; PCA projection: loadings/explained variance. |
| CRP-07 | Each execution | GARCH forecaster: the actual constrained fit and convergence/scoring state. EWMA is the fixed baseline. |
| CRP-09 | Each execution | Surprise scale: actual historical training scale and consensus identity. |
| ENS-COV | Each execution | Training covariance and constrained allocator, with their actual covariance/weights. |
| META-OOF | Each execution | Training standardizer and ridge metamodel, with actual scales/intercept/coefficients. |
| Validation TRAIN_MEAN | Each job | One distinct estimator per planned fold, retaining mean/training count or null when no fit occurred. |
| Validation OLS_LAG_RETURNS | Each job | Distinct standardizer and estimator per planned fold, retaining train-only means/scales, coefficients, rank policy and training count, or null. |

The ENS/META synthetic input prediction/return streams are prescribed test
inputs. This workflow does not pretend to fit their upstream source models.
Internal numerical optimization and diagnostic tests do not become extra
independent ensemble votes. Changing a requested variant still creates a new
actual Item8 attempt under the existing shared exposure controls.

## Runtime integration

`StudyModelIds(state, lab)` provides the following trusted, internal interface:

```python
base, actual_bytes, name = prepare_job(claimed_job.config)
configuration, input_manifest = models.register_study(
    user, claimed_job, base, actual_bytes
)
experiment_id = lab.begin_run(configuration, input_manifest, name=name)
state.bind(claimed_job.id, experiment_id)
bound_job = state.job(user, claimed_job.id)
result = models.execute_study(
    user, bound_job, experiment_id, configuration, input_manifest
)
lab.evaluate_run(experiment_id, result)
state.finish(claimed_job.id)
```

Runtime retains its existing exception/recovery authority; the bridge never
automatically replays numerical computation. `models.inspect(user, owned_job)`
returns the verified existing Lab projection. Current code/environment are
required for computation. Historical inspection follows retained producer
objects and job request; it does not regenerate old inputs using today's code.
Direct legacy runs without these bindings must be labelled legacy rather than
inventing retrospective preregistration. No client-supplied model receipt is an
authorization token.

Validation integrates the same bridge in its existing worker before Lab begin,
and its `get` verifies model receipts and actual per-fold parameters alongside
the temporal/quality graph. No new endpoint, lifecycle or dependency is needed.
Root Runtime/UI integration, full regression and governed CI remain separate
gates from this isolated module's focused tests.

## Proposed decision for integration

Status: proposed for root independent review and insertion into the durable
decision authority; no decision number is claimed here.

Apply the existing permanent-identity requirement to synthetic executable
Studies and chronological validation. Use immutable PROPOSED recipe records
and fresh per-execution/per-fold FIT child records, allocated before Item8
freeze; retain actual fitted parameters separately. Bind identities to owned
jobs and actual source bytes, and keep original shared-family exposure.

Rejected alternatives: retrospectively allocating IDs after fitting; reusing
one FIT ID for repeated jobs; labelling prescribed synthetic streams as trained
upstream models; creating artificial datasets/holdouts; changing model status
to VALIDATED after a software fixture; allocating new testing families to hide
variants; modifying Item8 to implement a second lifecycle. No methodological
equation, selection rule, scientific status or sealed-host boundary changes.

Consequences: old runs remain honestly inspectable through their existing
legacy path but do not gain preregistration claims. New prefit failures can
retain orphan proposed model records; this is intended evidence, not cleanup
debt. Canonical model records precede EXP, so their immutable later graph carries
the cross-reference instead of rewriting a prefit record.

## Executed isolated evidence

On the final production source, the root locked Python 3.14.7 interpreter ran
68 Studies/validation cases with `-W error` in 435.52s. All assertions passed,
but the explicit focused 90% coverage gate failed at 87.93%; that result is
retained, not described as a passing gate. Seventeen additional meaningful
defensive cases then passed in 20.87s against unchanged production source,
using coverage append: combined statement/branch 92.32%, model bridge 96.03%.
All 85 unique cases executed; this is two focused invocations, not a claim that
a single 85-case invocation or the full repository gate was run. Ruff and strict
mypy passed on the four production modules and both test modules.

The additional cases exercise closed/mismatched model graphs, actual failed
Item8 state, unexpected fitted outputs, stale family aliases, bounded immutable
objects, and contradictory fold fit/status evidence. Earlier exploratory test
failures were test-harness corrections (required bootstrap argument, proper
SHA256 prefix and exact object-store exception type); they were rerun in the
passing 68-case set. No production error was masked or coverage excluded.

The simulation peer independently read the full bridge and validation changes,
actual temporal fitting path and historical inspection regression, finding no
material blocker in that bounded source review. The peer did not rerun this
expanded suite. Root integration, full regression, browser proof and hosted CI
are still required before product-level completion claims.
