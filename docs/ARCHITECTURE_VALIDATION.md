# Architecture validation report

This report records the executable architecture-validation slice requested for JEVe. It is not a feature-completeness or EVE-integration report.

The slice deliberately uses one synthetic navigation/risk domain and Python standard-library code only. It exists to test whether the documented ownership boundaries remain coherent when represented as executable contracts.

## 1. Implemented surface

### `src/jeve/model.py`

Implements the value objects and authority-carrying types exercised by the slice:

- `Knowledge<T>` with distinct `KNOWN`, `UNKNOWN`, `STALE`, and `TRANSITIONAL` states;
- immutable `StateSnapshot`, `RouteState`, `Objective`, and `HardConstraints`;
- semantic `SemanticAction` values for `WAIT`, `TAKE_ROUTE(route_id)`, and `RETREAT(destination_id)`;
- stable reduction reason codes;
- `JudgmentOutputContract`, `JudgmentQuestion`, `JudgmentPlan`, `JudgmentResult`, raw `JudgmentBundle`, and `ValidatedJudgmentBundle`;
- policy, fresh-validation, execution-plan, delivery-evidence, and outcome-verification contracts.

### `src/jeve/pipeline.py`

Implements only the exercised architecture:

- deterministic candidate generation;
- deterministic reduction;
- deterministic judgment planning;
- fake/scripted JEV adapter;
- dependency-wave judgment scheduler;
- judgment-bundle validation;
- deterministic policy;
- fresh-state validation;
- simulated semantic-action compilation;
- simulated delivery;
- final-effect verification.

### `tests/test_architecture_slice.py`

Contains the nine requested evaluation fixtures plus narrow invariant tests required to demonstrate state semantics, reducer reason codes, and fresh precondition/constraint invalidation.

### `.github/workflows/architecture-validation.yml`

Runs the standard-library test suite on Python 3.12. GitHub Actions are pinned to resolved commit SHAs rather than floating tags.

## 2. Architecture that translated cleanly

### Deterministic -> probabilistic evidence -> deterministic policy

This boundary translated directly. Candidate generation and exact reduction produce a bounded semantic candidate set. The judgment planner sees only unresolved semantic dimensions. The JEV adapter returns evidence. The deterministic policy is the first component that selects a semantic action.

No JEV result type contains an execution hook, compiler reference, or physical input value.

Evidence:

- `JudgmentPlanner.plan`
- `FakeJEVAdapter.evaluate`
- `JudgmentBundleValidator.validate`
- `DeterministicPolicy.decide`
- fixture `test_fixture_2_parallel_route_risk_is_one_wave_and_policy_selects_semantic_action`

### Zero-JEV mechanical branch

The deterministic-only fixture resolves exact route risk mechanically. The planner emits no questions and the fake adapter call count remains zero.

Evidence:

- fixture `test_fixture_1_deterministic_only_uses_zero_jev_calls`

### Independent judgment scheduling

The two route-risk judgments and disengage judgment have no dependencies and therefore occupy one scheduler wave. The contract does not require serialization or wall-clock concurrency.

Evidence:

- `JudgmentScheduler.build_waves`
- fixture `test_fixture_2_parallel_route_risk_is_one_wave_and_policy_selects_semantic_action`

### Semantic action / physical execution separation

`SemanticAction` contains semantic identifiers only. `ExecutionPlan` is produced only after `ValidatedDecision`. The simulated physical step appears only in the compiler output.

Evidence:

- `SemanticAction`
- `ValidatedDecision`
- `SimulatedActionCompiler.compile`

### Delivery / final effect separation

Delivery evidence is represented independently from command acceptance, progress, and final effect. Success is true only when final semantic effect is verified.

Evidence:

- `ExecutionEvidence`
- `OutcomeVerifier.verify`
- fixtures `test_fixture_8_delivered_does_not_mean_final_effect` and `test_fixture_9_success_requires_verified_final_effect`

## 3. Architecture friction

### Friction A: raw bundle and policy-usable bundle are too easy to conflate in the documents

Documented assumption:

`JudgmentBundle` carries a `validation_status`, and deterministic policy consumes a validated judgment bundle.

Implementation pressure:

If raw and validated bundles share one structural type, callers can accidentally pass an invalid, partial, or stale bundle into policy and rely on runtime checks at every call site.

Assessment:

Missing contract.

Recommended change:

Keep `JudgmentBundle` as assembled evidence and introduce an explicit `ValidatedJudgmentBundle` (or equivalent capability type) that can be constructed only by bundle validation. Policy should consume the validated type.

The slice implements this distinction.

### Friction B: judgment freshness needs an explicit owner

Documented assumption:

Questions and results are bound to snapshot/epoch and carry freshness/dependency semantics.

Implementation pressure:

The minimum result schema does not fully specify where the concrete expiration decision lives. Validation needs a deterministic comparison point.

Assessment:

Missing contract / lifecycle detail.

Recommended change:

State explicitly that freshness policy is declared by the question/plan or policy configuration, normalized into a result-validity deadline/dependency token, and enforced by the bundle validator. The slice uses `fresh_until` only as the smallest executable representation of that contract.

### Friction C: provider failure and stale semantic evidence are different failure classes

Documented assumption:

Provider failure remains provider failure and must not become a guessed semantic value.

Implementation pressure:

A naive validator can apply freshness checks to every provider result object, causing an `ERROR` result with no semantic value to be classified as stale instead of missing required evidence.

Assessment:

Implementation detail that exposes an important semantic distinction.

Recommended change:

Freshness applies to returned semantic evidence. Provider `ERROR`/required `ABSTAIN` should remain evidence absence/failure unless the contract separately defines transport-result expiry.

The first executable test pass exposed this distinction; the validator was corrected so only `ANSWERED` semantic values participate in result-freshness validation.

### Friction D: generic `required_facts` on every semantic action is not needed yet

Documented assumption:

The detailed design illustrates `SemanticAction.required_facts`.

Implementation pressure:

For this slice, route/retreat preconditions already have a clear owner in normalized state, deterministic reduction, and fresh-state validation. Copying the same predicates into each action would duplicate information.

Assessment:

Unnecessary abstraction for the current slice.

Recommended change:

Do not require `required_facts` as stored action data until an implementation needs portable/declarative precondition descriptions. Preserve the invariant that fresh preconditions are rechecked, not the illustrative storage shape.

## 4. Invariants actually demonstrated

| Invariant | Executable evidence |
|---|---|
| `KNOWN`, `UNKNOWN`, `STALE`, `TRANSITIONAL` remain distinct | `test_knowledge_states_remain_distinct` |
| no unknown-like value silently becomes false | `Knowledge` construction rules and reducer handling |
| state snapshot is immutable by implementation | frozen dataclasses in `model.py` |
| semantic candidates contain no physical/provider values | `SemanticAction` |
| reducer emits stable typed elimination reasons | `test_reducer_emits_stable_reason_codes` |
| exact branch can use JEV call count = 0 | fixture 1 |
| judgment plan is deterministic for fixed inputs | deterministic question IDs/order and plan ID |
| ambiguous route scenario produces three independent questions | fixture 2 |
| one execution wave contains all three independent questions | fixture 2 |
| provider failure does not synthesize semantic value | `FakeJEVAdapter` + bundle validation |
| missing required judgment has no action authority | fixture 3 |
| SCORE cannot silently satisfy PROBABILITY | fixture 4 |
| calibrated probability requirement is enforced | fixture 5 |
| stale semantic evidence cannot enter policy | fixture 6 |
| JEV output never dispatches execution | type/ownership path through policy and validation |
| deterministic policy selects the semantic branch | fixture 2 |
| observation-epoch change invalidates an otherwise valid decision | fixture 7 |
| changed precondition rejects execution | `test_fresh_validation_rejects_precondition_and_constraint_changes` |
| incompatible hard-constraint change rejects execution | same test |
| stale decision is rejected rather than repaired into another action | `FreshStateValidator` returns failure only |
| `SemanticAction` and `ExecutionPlan` remain separate | compiler boundary |
| `DELIVERED` is not semantic success | fixture 8 |
| success requires observed `FINAL_EFFECT` | fixture 9 |

## 5. Unproven assumptions

This slice intentionally does not validate:

- real EVE observation, normalization, entity identity, or observation-epoch advancement rules;
- real JEV transport, provider batching, cancellation, timeout behavior, or calibration quality;
- statistical interpretation/correlation between parallel judgments;
- optional-judgment cancellation and policy short-circuit timing;
- deliberative escalation;
- selector-compatibility mode;
- pending-intent/resource ownership and duplicate suppression;
- replay persistence/metrics storage;
- provider-specific or physical executor integration;
- long-running state transitions;
- performance under real latency or concurrency.

These remain future work, not failures of the current slice.

## 6. Overengineering findings

The large illustrative directory tree should not be created yet.

The slice required only two source modules:

1. immutable contracts/value objects;
2. executable decision/evidence/execution pipeline.

Separate directories for observer, replay, traces, pending intents, clocks, deliberation, provider integration, or EVE integration would currently be empty ownership shells. They should be added only when an executable contract requires them.

The detailed `SemanticAction.required_facts`, consequence classes, resource claims, retry policies, and generalized predicate objects are also not needed to prove the requested boundary.

## 7. Missing abstractions

### Validated evidence capability

A raw `JudgmentBundle` repeatedly appears near the policy boundary, but the stronger concept is “bundle that has passed semantic validation for this policy context.” `ValidatedJudgmentBundle` is the missing capability type.

### Freshness decision contract

Freshness appears in snapshot, question dependencies, result lifecycle, and bundle validation. The architecture should name the owner of the final freshness decision more explicitly. The validator is the natural authority; adapters should report timestamps/dependencies, not decide policy usability.

No other new abstraction was required by this slice.

## 8. Architecture verdict

### Does the current JEVe architecture appear internally implementable as documented?

Yes for the validated core path.

The slice represents the documented boundary without circular ownership, provider concepts in core action types, duplicated mutable state, or a special JEV-to-execution fast path. The deliberate extra types around validation are justified by authority boundaries rather than framework generality.

### Boundaries that should remain unchanged

Keep these invariants unchanged:

- exact/mechanical reasoning before JEV;
- JEV as typed semantic evidence rather than action authority;
- independent judgments parallelizable by contract;
- explicit output semantics and calibration;
- deterministic policy as semantic action authority;
- explicit unknown/stale/transitional knowledge;
- fresh-state validation before compilation;
- semantic actions separate from physical plans;
- delivery/acceptance/progress/final effect separate;
- provider/client details behind adapters.

### Contracts to simplify or correct before broader implementation

1. Make raw-vs-validated judgment bundles structurally distinct.
2. Clarify ownership and representation of judgment freshness.
3. State explicitly that provider failure is evidence absence/failure, not stale semantic evidence.
4. Keep `required_facts`, generic predicate objects, resource claims, and large module trees illustrative until concrete use cases justify them.

## Next implementation direction

The next useful increment is not real EVE or a real JEV provider.

Add replay/trace ownership around the slice and one optional-evidence/short-circuit case, then add pending-intent/resource ownership. Those two increments will test lifecycle and replay claims that this slice does not yet exercise without forcing provider or UI integration.

After those boundaries survive executable tests, a real JEV adapter becomes a reasonable next volatile integration.
