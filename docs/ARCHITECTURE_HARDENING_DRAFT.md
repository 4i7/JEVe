# Architecture hardening status

This note records the authority and lifecycle contracts that were promoted from the temporary hardening wrapper into the owning JEVe core validation slice.

The temporary `src/jeve/validation_guards.py` layer has been deleted. There is now one policy/evidence authority path in `model.py` and `pipeline.py`.

## 1. Policy decision binding

A selected `PolicyDecision` now records:

```text
semantic_input_key
policy_config_key
created_at
expires_at
judgment_bindings[]
```

`semantic_input_key` is a canonical JSON-derived SHA-256 fingerprint of normalized semantic policy inputs rather than a hash of Python `repr(...)` output.

Each consumed judgment binding records:

```text
question_id
result_id
value kind
value
equivalence_key
provider_id
model_id
schema_version
dependency_key
valid_until
```

Fresh-state validation rejects the old decision when the normalized semantic inputs, policy configuration, consumed judgment identity/value, or bound evidence lifetime no longer match.

The current implementation intentionally remains conservative: the semantic snapshot key covers more normalized state than a future fine-grained dependency model may require.

## 2. Decision freshness

`PolicyConfig.decision_ttl` defines an explicit decision lifetime.

The policy records `created_at` and `expires_at`; fresh-state validation rejects a selected decision with `DECISION_EXPIRED` before compilation.

This is separate from snapshot freshness and judgment-evidence freshness.

## 3. Judgment evidence freshness through execution admission

The `JudgmentBundleValidator` owns semantic evidence lifetime through `JudgmentFreshnessPolicy.max_age`.

Provider-supplied `fresh_until` is not treated as policy authority.

The policy records the valid-until time of each judgment it actually consumed. Fresh-state validation checks those bindings again before execution admission and rejects expired evidence with `JUDGMENT_EVIDENCE_EXPIRED`.

## 4. Single evidence authority path

`ValidatedJudgmentBundle` has been removed from the validation slice.

Policy consumes only `PolicyUsableJudgmentBundle`, which is issued by `JudgmentBundleValidator` after type/range, required-result, freshness, correlation metadata, equivalence, and calibration checks pass.

The constructor uses an authority-owned seal to prevent accidental ordinary construction. This remains an application-level Python invariant, not a security boundary against hostile reflection.

## 5. Calibration provenance

A calibrated result now carries `CalibrationProvenance`:

```text
authority
basis
provider_id
model_id
schema_version
evaluation_population
metric_name
metric_value
```

A `CalibrationPolicy` declares the accepted authority set, evaluation population, metric name, and maximum accepted metric value for the current deployment/test policy.

The validator checks that provenance matches the result provider/model/schema and the configured calibration policy.

This proves provenance integrity and policy acceptance. It does not claim that one universal calibration metric or threshold is correct for every deployment.

## 6. Provider failure vs stale semantic evidence

`ERROR` remains `PROVIDER_FAILURE` and required-evidence absence.

Only an answered semantic result can become `RESULT_STALE`.

The two failure classes are tested separately.

## 7. Correlation and statistical fusion

Scheduling dependency and statistical correlation are separate contracts.

The route-risk and disengagement judgments share `current-route-risk-context` while remaining executable concurrently.

`ProbabilityFusion.product(...)` rejects multiplication when correlation keys repeat, even when the caller supplies an independence justification. It also requires an explicit non-empty justification before any independent-probability multiplication is allowed.

The current deterministic policy does not statistically fuse the route-risk/disengagement probabilities.

## 8. Judgment equivalence and reuse

Reuse now requires all of the following:

```text
explicit cross-snapshot reuse opt-in
ANSWERED semantic result
freshness still valid under validator policy
compatible observation epoch
provider_id match
model_id match
schema_version match
judgment equivalence_key match
semantic dependency_key match
```

`equivalence_key` describes judgment semantics/contract. `dependency_key` separately captures current feature values and declared freshness dependencies.

Cross-snapshot reuse remains disabled by default.

## 9. Actual concurrency and optional cancellation

`JudgmentScheduler.execute(...)` runs each dependency wave with a bounded `ThreadPoolExecutor` and restores deterministic result ordering afterward.

`execute_until_policy_sufficient(...)` demonstrates the optional-evidence lifecycle:

```text
start required + optional read-only work
-> wait for required evidence
-> policy-sufficiency predicate becomes true
-> signal optional cancellation
-> validate partial bundle with missing optional evidence allowed
-> deterministic policy proceeds
```

The fake adapter supports cooperative cancellation for this synthetic proof.

## 10. Pending intent and semantic resource ownership

`PendingIntentRegistry` provides the first state-changing admission boundary.

The current semantic navigation actions claim the `navigation` resource.

Admission rejects:

```text
same unresolved semantic action -> DUPLICATE_PENDING_INTENT
different action claiming an occupied resource -> RESOURCE_BUSY
```

Compilation requires an admitted pending intent matching the validated semantic action.

The resource is released explicitly when the pending intent is resolved.

## 11. Trace and replay

`DecisionTrace` captures the synthetic causal path:

```text
snapshot
reduction
judgment plan
judgment results
bundle validation status
judgment freshness policy
calibration policy identity
policy config identity
policy decision
fresh validation
execution plan
outcome
```

`ReplayRunner` revalidates the recorded judgment evidence and reruns deterministic policy. Replay rejects configuration or calibration-policy drift and requires the reproduced `PolicyDecision` to equal the recorded decision.

This is an in-memory replay proof, not yet a persistence format.

## 12. Remaining unproven provider/runtime behavior

The validation slice still does not prove real-provider behavior for:

- network/transport timeout semantics;
- cancellation after a request has reached the provider;
- rate-limit admission/backoff;
- provider-native batching or multi-output requests;
- partial streaming completion;
- real provider/model version discovery;
- real calibration study ingestion;
- wall-clock performance under production concurrency.

These belong behind a future real JEV adapter. Core authority should not be weakened to accommodate provider limitations.

## Current next direction

The previously proposed sequence:

```text
trace/replay
-> optional short-circuit/cancellation
-> pending intent/resource ownership
```

is now represented in the synthetic core slice.

The next useful increment is therefore a small adapter qualification boundary for a real JEV provider: normalize provider/model/schema identity, timeout/cancellation outcomes, rate-limit behavior, batching semantics, and partial completion into the already-proven core contracts.

Real EVE observation or physical execution integration should still wait until that provider boundary can be qualified without changing deterministic policy semantics.
