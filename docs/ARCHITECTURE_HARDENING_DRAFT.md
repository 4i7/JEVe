# Architecture hardening draft

This note is a deliberately small follow-up to `ARCHITECTURE_VALIDATION.md`.
It does not redefine the main architecture. It records the next contracts that
should be proven before adding real JEV/EVE integrations.

## 1. Bind policy decisions to all semantic inputs

Problem:

A selected `PolicyDecision` is currently bound to snapshot/epoch identity, but
that does not by itself prove that every semantic input the policy consumed is
still equivalent before execution.

Draft response:

- record a conservative semantic fingerprint when policy evaluates;
- include normalized objective, hard constraints, routes and other semantic
  state consumed by the policy;
- reject the old decision if the fresh normalized semantic fingerprint changes;
- do not mutate the old decision into a replacement action.

The draft intentionally fingerprints more state than strictly necessary. A
future dependency model may safely become finer-grained only after replay tests
prove that omitted fields cannot affect the decision.

## 2. Treat validated evidence as a capability

Problem:

`ValidatedJudgmentBundle(bundle)` is structurally distinguishable from a raw
bundle, but ordinary Python construction can still accidentally create it.

Draft response:

`PolicyUsableJudgmentBundle` requires an authority-owned seal and is issued only
by `EvidenceAuthority` after all guards pass.

This is not intended as a security boundary against hostile Python code.
Python reflection/private-name access can bypass application-level conventions.
The goal is to make accidental construction invalid and to make the authority
boundary explicit in normal code.

## 3. Calibration needs evidence, not only an enum

Problem:

`CALIBRATED` currently states a conclusion without recording why that conclusion
is justified.

Draft response:

A calibrated result entering policy must also carry `CalibrationEvidence`:

```text
authority
basis
```

The draft does not prescribe a universal calibration method. Real providers may
later normalize a documented provider guarantee, measured calibration study, or
operator-approved calibration profile into this contract.

Until such evidence exists, a `CALIBRATED` enum alone is insufficient.

## 4. Freshness authority

Problem:

A provider result currently contains `fresh_until`, which can blur the boundary
between provider metadata and policy usability.

Draft response:

- provider/result reports `completed_at`;
- `EvidenceAuthority` owns the allowed semantic evidence age;
- provider-supplied `fresh_until` is ignored by the hardening draft;
- snapshot freshness remains a separate normalized-state concern;
- execution freshness remains owned by the fresh-state validator.

This creates three explicit responsibilities:

```text
provider: when the result completed
bundle/evidence authority: whether semantic evidence is still policy-usable
fresh-state validator: whether the selected action is still executable now
```

## 5. Provider failure is not stale semantic evidence

A provider `ERROR` means no semantic answer was produced.
It therefore remains provider/evidence failure and required-evidence absence.

`RESULT_STALE` applies only to an answered semantic value whose authority-owned
freshness budget expired.

The draft adds an explicit `PROVIDER_FAILURE` guard reason so diagnostics do not
collapse these two lifecycle states.

## 6. Correlation is separate from scheduling independence

Questions may be executable concurrently while sharing evidence/context and
therefore being statistically correlated.

For the route-risk slice:

```text
ROUTE_RISK(route_a)
ROUTE_RISK(route_b)
SHOULD_DISENGAGE(current_context)
```

share `current-route-risk-context` as a correlation key.

The correlation key does not serialize execution. It exists to prevent future
policy/statistical code from assuming that same-wave execution implies
independent probabilities.

No multiplication or probabilistic fusion of these values is introduced by the
draft.

## 7. `equivalence_key` and judgment reuse

Reuse must not be keyed only by `question_id`, prompt text, time proximity, or
snapshot identity.

The draft derives a conservative equivalence key from:

```text
judgment_type
subject_id
feature_slice
output value kind
output semantics
numeric range
calibration requirement
abstention contract
```

Cross-snapshot reuse remains disabled by default even when the key matches.
The key is a prerequisite for future reuse, not permission by itself.

A future reuse implementation must additionally prove freshness/dependency
compatibility and provider/model/schema compatibility where those affect
semantics.

## 8. Parallel means actual concurrent execution

The first slice represented dependency waves correctly but executed each member
serially.

`ConcurrentJudgmentScheduler` now executes members of one dependency wave via a
bounded `ThreadPoolExecutor` and restores deterministic result order afterward.

This is still only a synthetic runtime proof. It does not establish real-provider
latency, cancellation, rate-limit behavior, or batching semantics.

## 9. Next increments

Keep the next work in this order:

```text
1. trace/replay ownership
2. optional-evidence policy short-circuit + cancellation
3. pending-intent / semantic-resource ownership
```

Only after these lifecycle boundaries have executable evidence should the
project prioritize a real JEV adapter.

The reason for this ordering is that real integration would otherwise make
replay, evidence lifetime, cancellation, and duplicate state-changing intent
harder to separate from provider/client bugs.

## Draft status

The implementation in `src/jeve/validation_guards.py` is intentionally a draft
layer around the first validation slice rather than a large rewrite of
`model.py` / `pipeline.py`.

If its tests remain useful after review, the next change should fold the proven
contracts into the owning core types and delete the wrapper layer rather than
maintaining two permanent policy/evidence paths.
