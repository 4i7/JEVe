# Architecture validation report

This report records the executable architecture-validation slice for JEVe. It is not a feature-completeness or real EVE/JEV integration report.

The slice deliberately uses one synthetic navigation/risk domain and Python standard-library code only. Its purpose is to test whether the documented authority, freshness, evidence, policy, execution, and replay boundaries remain coherent when expressed as executable contracts.

## 1. Implemented surface

### `src/jeve/model.py`

Implements the value objects and authority-carrying types exercised by the slice:

- `Knowledge<T>` with distinct `KNOWN`, `UNKNOWN`, `STALE`, and `TRANSITIONAL` states;
- immutable `StateSnapshot`, `RouteState`, `Objective`, and `HardConstraints`;
- semantic `SemanticAction` values for `WAIT`, `TAKE_ROUTE(route_id)`, and `RETREAT(destination_id)`;
- stable reduction reason codes;
- typed judgment questions/results/contracts and raw `JudgmentBundle`;
- `PolicyUsableJudgmentBundle` as the single policy evidence capability;
- calibration provenance and calibration-policy contracts;
- explicit policy decision binding and temporal freshness fields;
- fresh-validation, pending-intent, resource-ownership, execution, outcome, trace, and replay contracts.

### `src/jeve/pipeline.py`

Implements only the exercised architecture:

- deterministic candidate generation and reduction;
- deterministic judgment planning;
- fake/scripted JEV adapter;
- dependency-wave scheduling with actual concurrent execution inside a wave;
- optional-evidence short-circuit with cooperative cancellation;
- judgment-bundle validation and validator-owned evidence freshness;
- deterministic policy with complete semantic/config/evidence binding;
- fresh-state validation including decision/evidence expiry checks;
- pending-intent duplicate suppression and semantic-resource admission;
- simulated semantic-action compilation and delivery;
- final-effect verification;
- trace assembly and deterministic replay.

### `tests/test_architecture_slice.py`

Contains the original nine required evaluation fixtures plus authority/lifecycle regression tests for the hardening work.

### `.github/workflows/architecture-validation.yml`

Runs the standard-library test suite on Python 3.12. GitHub Actions are pinned to immutable commit SHAs.

## 2. Architecture that translated cleanly

### Deterministic -> probabilistic evidence -> deterministic policy

Candidate generation and exact reduction produce a bounded semantic candidate set. The judgment planner sees only unresolved semantic dimensions. JEV returns typed evidence. The bundle validator decides whether that evidence is policy-usable. Deterministic policy is the first component that selects a semantic action.

No JEV result type contains an execution hook, compiler reference, or physical input value.

### Zero-JEV mechanical branch

A deterministic-only fixture resolves exact route risk mechanically. The planner emits no questions and the adapter call count remains zero.

### Concurrent judgments without independence assumptions

Independent scheduling dependencies can be executed concurrently in one wave. Statistical correlation is represented separately from scheduling dependency.

The route-risk and disengagement judgments share a correlation key in the synthetic scenario, so same-wave execution does not imply independent probabilities.

### Semantic action / physical execution separation

`SemanticAction` contains semantic identifiers only. Physical steps appear only after fresh validation and pending-intent admission.

Compilation may not silently replace one semantic action with another.

### Delivery / final effect separation

Delivery evidence remains distinct from command acceptance, progress, and final effect. Final success requires an observed semantic final effect.

## 3. Authority and lifecycle findings

### Raw evidence vs policy-usable evidence

The initial slice exposed a real authority gap: a structurally validated bundle was still too easy to construct or pass through an older path.

The final slice removes the temporary dual path. Policy consumes only `PolicyUsableJudgmentBundle`, issued by `JudgmentBundleValidator` after the configured checks pass.

The constructor seal is an application-level invariant that prevents accidental ordinary construction. It is not claimed as a hostile-code security boundary.

### Freshness has explicit owners

Freshness is split by responsibility:

```text
provider/result -> completion time and provider metadata
bundle validator -> semantic judgment evidence lifetime
policy -> decision lifetime
fresh-state validator -> execution-time admission against current state/evidence
```

Provider-supplied expiry is not treated as policy authority.

### Provider failure is not stale evidence

A provider `ERROR` means no semantic answer exists. It is classified as provider/evidence failure and required-evidence absence.

Only an answered semantic value can become stale.

### Policy decisions are bound to what they consumed

A selected decision records bindings for:

```text
canonical normalized semantic input fingerprint
policy configuration fingerprint
created_at / expires_at
consumed judgment result identity
consumed judgment value/type
judgment equivalence key
dependency key
provider/model/schema identity
evidence valid-until time
```

Fresh validation rejects the old decision when any bound policy input changes or expires.

### Canonical binding is explicit

Semantic fingerprints use canonical JSON-derived material before SHA-256 hashing. They do not depend on Python `repr(...)` stability.

The current fingerprint is intentionally conservative and may include more normalized semantic state than a future fine-grained dependency model requires.

### Calibration requires provenance

`CALIBRATED` is insufficient by itself. A calibrated result also carries provenance including authority, basis, provider/model/schema identity, evaluation population, metric name, and metric value.

`CalibrationPolicy` decides which provenance is accepted for the current deployment/test configuration.

This validates provenance integrity and policy compatibility; it does not claim that one universal calibration method is correct for every provider or deployment.

### Correlation is not silently ignored

The current deterministic policy does not statistically fuse route-risk/disengagement probabilities.

The synthetic probability-fusion helper rejects multiplication when the same correlation key appears and requires an explicit independence justification before any product of supposedly independent probabilities is permitted.

### Judgment reuse is fail-closed

Cross-snapshot reuse remains disabled by default.

When explicitly enabled, the synthetic compatibility check requires compatible:

```text
answer status
freshness
observation epoch
provider identity
model identity
schema version
equivalence key
dependency key
```

This demonstrates the reuse boundary without making reuse a default optimization.

## 4. Invariants actually demonstrated

| Invariant | Executable evidence |
|---|---|
| `KNOWN`, `UNKNOWN`, `STALE`, `TRANSITIONAL` remain distinct | knowledge-state tests |
| unknown-like values do not silently become false | construction/reducer tests |
| normalized snapshots are immutable | frozen dataclasses |
| semantic candidates contain no physical/provider values | semantic action contracts |
| reducer emits stable typed elimination reasons | reducer reason-code fixture |
| exact branch can use JEV call count = 0 | deterministic-only fixture |
| judgment plan is deterministic for fixed inputs | deterministic IDs/order |
| independent questions execute concurrently in one wave | scheduler concurrency fixture |
| same-wave execution does not imply probability independence | correlation tests |
| provider failure does not synthesize semantic value | provider-failure fixture |
| provider failure is distinct from stale answered evidence | validation tests |
| missing required judgment has no action authority | required-missing fixture |
| SCORE cannot silently satisfy PROBABILITY | semantic-output fixture |
| calibrated evidence requires accepted provenance | calibration tests |
| validator owns judgment evidence freshness | freshness tests |
| policy consumes only authority-issued usable evidence | capability-construction test |
| policy config is bound into the decision | config-drift test |
| consumed judgment identity/value is bound into the decision | evidence-drift test |
| decision TTL is enforced before execution | decision-expiry test |
| consumed judgment expiry is rechecked before execution | evidence-expiry test |
| normalized semantic input drift invalidates old decision | semantic-drift test |
| observation-epoch change invalidates an otherwise valid decision | epoch-change fixture |
| semantic fingerprints are canonical/stable for equivalent input | canonicalization test |
| correlated probabilities are not multiplied as independent | fusion rejection test |
| cross-snapshot reuse is fail-closed by default | reuse tests |
| optional work can be cancelled after required evidence is sufficient | short-circuit fixture |
| duplicate unresolved state-changing intent is suppressed | pending-intent test |
| conflicting semantic resource ownership is rejected | resource-admission test |
| semantic action and physical plan remain separate | compiler boundary |
| `DELIVERED` is not semantic success | delivery fixture |
| success requires observed `FINAL_EFFECT` | final-effect fixture |
| replay reproduces the deterministic decision under identical inputs | trace/replay test |

## 5. Original nine requested fixtures

The original architecture-validation request remains covered:

1. deterministic-only -> zero JEV calls;
2. ambiguous route risk -> multiple typed questions in one wave;
3. missing required judgment -> no action authority;
4. invalid semantic output kind -> rejected;
5. insufficient calibration -> rejected;
6. stale bundle/evidence -> rejected;
7. observation-epoch change -> execution rejected;
8. delivered but incomplete -> not success;
9. verified final effect -> success only after semantic verification.

## 6. Lifecycle increments now represented

The previously proposed next sequence has been implemented synthetically:

```text
trace/replay
-> optional-evidence short-circuit + cancellation
-> pending-intent / semantic-resource ownership
```

This means the next uncertainty is no longer basic core lifecycle ownership.

## 7. Remaining unproven assumptions

This slice intentionally does not validate:

- real EVE observation, entity identity, normalization, or observation-epoch advancement rules;
- real JEV network/transport timeout semantics;
- cancellation after a request has reached a real provider;
- rate-limit admission/backoff;
- provider-native batching or multi-output calls;
- partial/streaming completion semantics;
- real provider/model/schema identity discovery;
- real calibration-study ingestion and empirical quality;
- production wall-clock performance under real provider concurrency;
- deliberative escalation;
- selector-compatibility mode against a real provider;
- persistence format/durability for traces;
- real physical executor integration;
- long-running EVE state transitions.

These remain future integration/qualification work, not hidden assumptions of the current core path.

## 8. Overengineering findings

The large illustrative module tree is still unnecessary.

The synthetic architecture is intentionally concentrated in two source modules:

1. immutable contracts/value objects;
2. executable decision/evidence/execution/replay pipeline.

Separate provider, observer, persistence, or EVE integration packages should be added only when their actual contracts are implemented.

Generic declarative predicate frameworks, large plugin systems, databases, and provider-specific abstractions are still not justified by this slice.

## 9. Architecture verdict

The current synthetic JEVe core appears internally implementable with a single authority path and without circular ownership or a JEV-to-execution shortcut.

The boundaries that should remain unchanged are:

- exact/mechanical reasoning before JEV;
- JEV as typed semantic evidence rather than action authority;
- explicit uncertainty and calibration provenance;
- scheduling concurrency separate from statistical independence;
- deterministic policy as semantic action authority;
- complete policy-input binding through execution admission;
- explicit decision and evidence freshness;
- semantic actions separate from physical plans;
- pending-intent/resource admission before state-changing dispatch;
- delivery/acceptance/progress/final effect kept distinct;
- provider/client volatility isolated behind adapters;
- replayability of deterministic core decisions.

## 10. Next implementation direction

The next useful increment is a small real-JEV adapter qualification boundary, not EVE observation or physical execution.

It should prove that a real provider can normalize the following into the existing core contracts without changing deterministic policy semantics:

```text
provider/model/schema identity
timeout outcomes
cancellation outcomes
rate-limit behavior
batching/multi-output semantics
partial completion
calibration provenance input
wall-clock concurrency behavior
```

Only after that boundary is qualified should real EVE observation or physical execution integration become the next priority.
