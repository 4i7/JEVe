# JEVe Detailed Design

This document translates the architecture into implementation-ready contracts without prescribing concrete functions, libraries, or a programming language.

The intended reader is a human or AI coding agent preparing an MVP.

## 1. Design goals

The implementation should make the following properties obvious in code structure:

- deterministic facts and rules are separate from probabilistic semantic judgments;
- JEV is primarily a semantic evidence provider, not an executor or final authority;
- independent semantic judgments can run concurrently;
- deterministic policy combines exact state, constraints, candidate space, and validated judgments;
- semantic actions remain separate from physical operations;
- stale judgments and stale decisions are rejected rather than patched with guesses;
- uncertainty is explicit in state and in judgment output semantics;
- action outcome is verified from observation;
- every policy branch can be replayed offline;
- provider/client-specific integration details are isolated behind adapters.

## 2. Suggested module boundaries

A language-neutral module layout:

```text
core/
  state/
  candidates/
  reduction/
  judgments/
    planning/
    contracts/
    validation/
  policy/
  validation/
  actions/
  verification/
  traces/

adapters/
  observer/
  jev/
  deliberative/
  executor/

runtime/
  decision-loop/
  judgment-scheduler/
  pending-intents/
  clocks/

replay/
  scenarios/
  runner/

integration/
  eve/
    observation/
    semantic-mapping/
    execution/
```

The exact directory names may vary. Preserve the ownership boundaries.

## 3. Core value objects

The following shapes are illustrative schemas, not required source syntax.

### 3.1 Knowledge value

```text
Knowledge<T> = {
  status: KNOWN | UNKNOWN | STALE | TRANSITIONAL,
  value?: T,
  observed_at?: timestamp,
  source?: provenance,
  confidence?: number
}
```

For boolean facts, `KNOWN` carries either `true` or `false`.

Do not create convenience conversions that map `UNKNOWN`, `STALE`, or `TRANSITIONAL` to false.

### 3.2 State snapshot

```text
StateSnapshot = {
  snapshot_id: string,
  observation_epoch: integer|string,
  state_epoch: integer|string,
  observed_at: timestamp,
  freshness: FreshnessPolicy,
  facts: DomainState,
  objectives: ObjectiveSet,
  constraints: ConstraintSet,
  provenance: ProvenanceSummary
}
```

A snapshot is immutable after publication.

### 3.3 Objective

```text
Objective = {
  id: string,
  kind: enum|string,
  priority: number,
  parameters: map,
  completion_predicate: semantic predicate,
  expiration?: timestamp
}
```

Examples:

```text
REACH_DESTINATION(destination_id)
PRESERVE_SHIP
MAINTAIN_DISTANCE(target_id, range_band)
LEAVE_DANGEROUS_STATE
```

An objective describes a desired state, not a physical command sequence.

### 3.4 Constraint

```text
Constraint = {
  id: string,
  kind: HARD | SOFT,
  predicate: semantic predicate,
  reason_code: string
}
```

Hard constraints may eliminate actions. Soft constraints may influence policy but must not masquerade as hard safety rules.

### 3.5 Semantic action

```text
SemanticAction = {
  candidate_id: string,
  action_type: string,
  parameters: map<string, semantic_id|primitive>,
  required_facts: list<FactRequirement>,
  resource_claims: list<SemanticResource>,
  consequence_class: LOW | MEDIUM | HIGH,
  metadata: map
}
```

Physical references such as screen coordinates must not appear here.

### 3.6 Candidate set

```text
CandidateSet = {
  generated_from_snapshot: snapshot_id,
  objective_id: string,
  candidates: SemanticAction[],
  generation_notes: ReasonCode[]
}
```

Candidate generation should be complete with respect to the currently supported action vocabulary. If completeness cannot be established, surface that fact explicitly.

### 3.7 Reduction result

```text
ReductionResult = {
  input_candidate_ids: string[],
  surviving_candidates: SemanticAction[],
  eliminated: [
    {
      candidate_id: string,
      reason_code: string,
      evidence_refs: string[]
    }
  ],
  unresolved_dimensions: string[]
}
```

Every eliminated candidate needs a deterministic reason.

### 3.8 Judgment output contract

```text
JudgmentOutputContract = {
  value_kind:
    PROBABILITY | SCORE | BOOLEAN | ENUM | RANKING | DISTRIBUTION,
  semantics: string,
  range?: [number, number],
  enum_values?: string[],
  calibration_requirement?: NONE | DECLARED | CALIBRATED,
  abstention_allowed: boolean
}
```

The `semantics` field defines what a value means. Encoding alone is insufficient.

### 3.9 Judgment question

```text
JudgmentQuestion = {
  question_id: string,
  judgment_type: string,
  subject?: SemanticReference,
  feature_slice: map,
  output_contract: JudgmentOutputContract,
  criticality: REQUIRED | OPTIONAL,
  depends_on: string[],
  freshness_dependencies: string[],
  deadline?: timestamp,
  equivalence_key?: string
}
```

A question asks for semantic evidence, not a physical operation.

### 3.10 Judgment plan

```text
JudgmentPlan = {
  plan_id: string,
  snapshot_id: string,
  observation_epoch: integer|string,
  objective_id: string,
  questions: JudgmentQuestion[],
  required_question_ids: string[],
  optional_question_ids: string[],
  deadline?: timestamp,
  schema_version: string
}
```

The plan should be deterministic for the same normalized state, policy requirements, and configuration.

### 3.11 Judgment result

```text
JudgmentResult<T> = {
  question_id: string,
  status: ANSWERED | ABSTAIN | NEED_MORE_INFORMATION | ERROR,
  value?: T,
  confidence?: number,
  calibration: CALIBRATED | UNCALIBRATED | UNKNOWN | NOT_APPLICABLE,
  requested_features?: string[],
  snapshot_id: string,
  observation_epoch: integer|string,
  completed_at: timestamp,
  adapter_metadata?: map
}
```

`confidence` is advisory evidence quality metadata, not action authority.

### 3.12 Judgment bundle

```text
JudgmentBundle = {
  bundle_id: string,
  plan_id: string,
  snapshot_id: string,
  observation_epoch: integer|string,
  results: map<question_id, JudgmentResult>,
  missing_required: string[],
  missing_optional: string[],
  validation_status: VALID | PARTIAL | INVALID | STALE,
  completed_at: timestamp,
  timings: map<string, duration>
}
```

A partial bundle may be policy-usable only when every missing result is explicitly optional for the branch being evaluated.

### 3.13 Policy decision

```text
PolicyDecision = {
  transaction_id: string,
  status:
    SELECTED | OBSERVE_MORE | DELIBERATE | WAIT | FAIL_CLOSED,
  selected_candidate_id?: string,
  reason_codes: string[],
  judgment_refs: string[],
  policy_version: string,
  evaluated_snapshot_id: string,
  observation_epoch: integer|string
}
```

This is the first object that states which semantic branch the system intends to take.

### 3.14 Validated decision

```text
ValidatedDecision = {
  transaction_id: string,
  selected_action: SemanticAction,
  validation_snapshot_id: string,
  validation_observation_epoch: integer|string,
  validation_reason: string,
  expires_at?: timestamp
}
```

This is the first object eligible for compilation into physical execution.

### 3.15 Execution plan

```text
ExecutionPlan = {
  plan_id: string,
  semantic_action: SemanticAction,
  compiled_from_snapshot: string,
  observation_epoch: integer|string,
  steps: PhysicalStep[],
  acceptance_predicate?: semantic predicate,
  progress_predicate?: semantic predicate,
  final_effect_predicate: semantic predicate,
  timeout_policy: TimeoutPolicy,
  retry_policy: RetryPolicy,
  resource_claims: SemanticResource[]
}
```

Retries should default to none unless the action-specific design proves a safe retry condition.

### 3.16 Decision trace

```text
DecisionTrace = {
  trace_id: string,
  snapshot_ref: string,
  candidate_generation: summary,
  reduction: summary,
  judgment_plan?: summary,
  judgment_results?: summary,
  bundle_validation?: summary,
  policy: summary,
  fresh_validation: summary,
  execution?: summary,
  outcome?: summary,
  timings: map<string, duration>
}
```

Replay must be possible without the live client.

## 4. Processing pipeline

### Stage A: observe

Input:

```text
external state
```

Output:

```text
RawObservation
```

Rules:

- do not infer semantics that belong to normalization or judgment;
- preserve acquisition time and source identity;
- distinguish source failure from observed absence.

### Stage B: normalize

Input:

```text
RawObservation
```

Output:

```text
StateSnapshot
```

Rules:

- convert source-specific values into domain facts;
- label unknowns explicitly;
- calculate cheap exact derived facts;
- establish epoch/freshness metadata;
- reject contradictions rather than silently choosing one source.

### Stage C: generate candidates

Input:

```text
StateSnapshot + active objectives
```

Output:

```text
CandidateSet
```

Rules:

- generate semantic, not physical, alternatives;
- do not generate actions forbidden by static capability configuration;
- parameterize by semantic IDs;
- keep the set relevant to current objectives and state.

### Stage D: deterministic reduction

Input:

```text
StateSnapshot + CandidateSet
```

Output:

```text
ReductionResult
```

Suggested reduction order:

1. schema/parameter validity;
2. capability availability;
3. hard preconditions;
4. hard safety constraints;
5. objective relevance;
6. exact resource/timer/range constraints;
7. pending-intent conflict;
8. strict dominance under exact dimensions;
9. operator policy filters.

Do not use JEV inside deterministic reduction.

### Stage E: pre-judgment policy check

Before planning JEV work, ask whether exact state already determines the branch.

Examples:

```text
0 candidates -> OBSERVE_MORE or FAIL_CLOSED
1 candidate + all policy requirements exact -> SELECT without JEV
hard emergency rule -> deterministic emergency action
objective already satisfied -> no action
```

The purpose is to avoid semantic calls that cannot change the outcome.

### Stage F: judgment planning

Input:

```text
StateSnapshot
ReductionResult
PolicyEvidenceRequirements
```

Output:

```text
JudgmentPlan
```

Rules:

- identify only unresolved semantic dimensions that can affect policy;
- prefer small typed questions over one monolithic action-selection request;
- mark required vs optional questions;
- declare dependencies explicitly;
- assign per-question output semantics;
- bind questions to freshness dependencies;
- project only relevant features.

Example:

```text
Q1 hostile_probability(contact_17)
Q2 route_risk(route_a)
Q3 route_risk(route_b)
Q4 disengage_probability(context)
```

### Stage G: schedule judgments

The scheduler constructs execution waves from `depends_on`.

Questions with no unsatisfied dependency may execute concurrently.

Rules:

- enforce plan and per-question deadlines;
- support cancellation;
- keep question identities stable for tracing;
- do not serialize independent questions without a reason;
- do not infer physical authority from concurrency.

Provider-native multi-output batching and multiple parallel provider calls are both valid implementations if they preserve question/result correlation.

### Stage H: JEV evaluation

The adapter should:

1. serialize a typed semantic question or provider-native batch;
2. enforce deadlines/cancellation;
3. parse output strictly;
4. validate basic type/range constraints;
5. preserve abstention and provider errors as data;
6. record latency and provider metadata;
7. never convert transport failure into a semantic value.

### Stage I: bundle assembly and validation

Input:

```text
JudgmentPlan + JudgmentResults
```

Output:

```text
JudgmentBundle
```

Checks include:

```text
question/result correlation
snapshot/epoch binding
value kind and range
required result presence
calibration requirement
freshness
contract-specific consistency
```

A numeric output with the wrong semantic type is invalid even if its numeric range looks plausible.

### Stage J: deterministic policy

Input:

```text
StateSnapshot
ReductionResult.surviving_candidates
ConstraintSet
JudgmentBundle
PolicyConfig
```

Output:

```text
PolicyDecision
```

The policy must be deterministic for identical validated inputs and configuration.

Possible implementation styles:

```text
rule table
threshold policy
finite state machine
deterministic utility calculation
configured weighted scoring
hysteresis-based branch logic
```

The policy may return a non-action route rather than forcing selection.

### Stage K: deliberative escalation

Escalate when, for example:

```text
required judgment schema is missing
candidate generation is itself uncertain
novel state exceeds fast-path policy
critical judgments conflict under an explicit invariant
consequence class exceeds accepted evidence quality
objectives conflict beyond deterministic policy
```

The deliberative layer must return to deterministic policy or semantic-action validation. It cannot directly dispatch physical input.

### Stage L: fresh-state validation

Before compilation, validate the selected semantic action against a sufficiently fresh current snapshot.

Check:

```text
selected candidate still exists
required semantic entities still exist
hard preconditions still hold
relevant constraints unchanged
observation epoch compatible
pending intent compatible
freshness budget acceptable
higher-priority inhibit absent
```

A policy decision made from valid judgments can still become invalid before execution.

### Stage M: compile

The compiler consumes only a validated semantic action plus current state.

It may return:

```text
COMPILED(plan)
NEEDS_OBSERVATION(feature_set)
UNSUPPORTED(reason)
INHIBITED(reason)
```

It must not silently choose a different semantic action.

### Stage N: dispatch and verify

A generic transaction shape:

```text
compile
-> dispatch bounded step
-> observe
-> acceptance check
-> observe
-> progress check if applicable
-> observe
-> final-effect check
```

The exact physical sequence is action-specific.

## 5. Fast judgment design

### 5.1 Judgment-first semantic decomposition

The normal fast path should ask for semantic quantities that deterministic policy can compose.

Prefer:

```text
threat probability
route risk
engagement suitability
disengagement suitability
target preference
```

over:

```text
"What action should I take?"
```

when the decomposition is meaningful.

Benefits include:

- reusable outputs;
- smaller contexts;
- explicit semantics;
- parallel execution;
- deterministic policy control;
- easier replay and threshold tuning.

### 5.2 When not to decompose

Do not create decomposition merely to satisfy the architecture.

A closed-candidate preference judgment is reasonable when:

- the unresolved semantic property is inherently comparative;
- the alternatives are already known and bounded;
- separate component scores would be artificial or misleading;
- no reusable sub-judgment is gained.

Represent selector mode as a judgment result consumed by policy.

### 5.3 Feature locality

Feature slices should be selected per judgment type and subject.

A feature dependency registry may look like:

```text
JudgmentType -> RequiredFeatureGroups
JudgmentType + SubjectKind -> OptionalFeatureGroups
```

Avoid serializing unrelated world state into each model call.

### 5.4 Parallelism

Independent questions should be scheduled in the same wave.

Measure:

```text
sum_of_question_latencies
required_bundle_wall_clock_latency
```

The difference between these values reveals the benefit of parallel execution.

### 5.5 Policy sufficiency and early completion

The policy does not need every optional judgment if the required evidence already determines the branch.

Example:

```text
required hostile_probability complete
required disengage_probability complete
policy returns RETREAT
optional target_preference still running
```

The scheduler may cancel the optional question.

### 5.6 Caching

Safe cache keys should describe semantic dependency equivalence, not merely time proximity.

Candidates for caching:

- static domain metadata;
- exact derived features;
- feature projections;
- judgment results whose declared dependencies and semantic contract are unchanged.

A conservative MVP may invalidate all judgments whenever the snapshot changes.

### 5.7 Early cancellation

If a new observation invalidates required judgment dependencies, cancel outstanding work when possible.

Stale results may be retained in diagnostics but not passed to policy as current evidence.

### 5.8 Decision stability

Fast loops can oscillate even when judgment outputs differ only slightly.

Use deterministic mechanisms such as:

- hysteresis;
- minimum semantic-intent hold time where appropriate;
- pending-intent suppression;
- explicit decision-equivalence keys;
- state-change requirements before reconsideration.

These belong to runtime/policy, not prompt wording.

## 6. Judgment scale and calibration

### 6.1 Probability

Use `PROBABILITY` only when the output contract gives the value probability semantics and policy accepts its calibration status.

### 6.2 Score

Use `SCORE` for relative or ordinal semantic evidence where calibrated probability is not claimed.

Scores should declare comparability, for example:

```text
comparable only within the same judgment type and schema version
```

### 6.3 Confidence

Confidence is metadata about a result, not a replacement for calibration.

A policy may use it to request more evidence or escalate, but not as proof.

### 6.4 Combining outputs

Do not perform statistical operations that assume independence unless independence is justified.

In particular, do not blindly multiply probability-like judgments merely because they were evaluated in parallel.

Parallel evaluation is a latency property. Statistical independence is a semantic property.

## 7. Deterministic policy design

Policy owns final semantic branching.

A useful policy contract is:

```text
Policy.evaluate(
  state,
  candidates,
  constraints,
  judgments,
  config
) -> PolicyDecision
```

Policy should expose stable reason codes.

Illustrative logic:

```text
if hard_safety_rule_requires_retreat:
    SELECT(RETREAT, reason=HARD_SAFETY)

else if required_judgment_missing:
    OBSERVE_MORE(reason=MISSING_REQUIRED_EVIDENCE)

else if judgment_quality_below_required_level:
    DELIBERATE(reason=EVIDENCE_QUALITY)

else:
    evaluate configured semantic thresholds and choose from valid candidates
```

Policy configuration should be externalized rather than hidden inside adapters.

## 8. Semantic resource ownership

A semantic action may claim one or more resources, for example:

```text
navigation
target_selection
engagement
inventory_interaction
```

The MVP may use a single-writer map:

```text
resource -> pending_intent_id
```

A conflicting new action is rejected, deferred, or deliberately replaces the owner under explicit policy.

## 9. Failure taxonomy

Use typed failure categories.

Suggested categories:

```text
OBSERVATION_UNAVAILABLE
OBSERVATION_CONTRADICTORY
STATE_STALE
NO_VALID_CANDIDATE
INSUFFICIENT_EXACT_EVIDENCE
JUDGMENT_PLAN_UNAVAILABLE
JUDGMENT_TIMEOUT
JUDGMENT_TRANSPORT_ERROR
JUDGMENT_INVALID_RESPONSE
JUDGMENT_ABSTAIN
JUDGMENT_REQUIRED_MISSING
JUDGMENT_CALIBRATION_INSUFFICIENT
JUDGMENT_BUNDLE_STALE
JUDGMENT_BUNDLE_INVALID
NOVEL_STATE
POLICY_NO_BRANCH
VALIDATION_FAILED
EPOCH_CHANGED
ACTION_UNSUPPORTED
ACTION_INHIBITED
EXECUTION_DELIVERY_FAILED
COMMAND_NOT_ACCEPTED
ACTION_STALLED
FINAL_EFFECT_NOT_OBSERVED
```

Each failure should map to a deterministic next-step policy such as:

```text
REOBSERVE
REASK_SELECTED_JUDGMENTS
DELIBERATE
WAIT
FAIL_CLOSED
REQUEST_OPERATOR
```

Avoid generic unbounded retry.

## 10. Configuration

Separate configuration into at least:

```text
JudgmentPolicy
ActionPolicy
SafetyPolicy
FreshnessPolicy
AdapterConfig
TracePolicy
```

Example judgment policy fields:

```text
max_parallel_questions
question_deadline_ms
bundle_deadline_ms
allowed_partial_bundle
required_calibration_by_judgment_type
```

Example action policy fields:

```text
thresholds by judgment type
stakes-specific evidence requirements
hysteresis settings
novelty thresholds
selector-mode acceptance rules
```

Do not hard-code these values inside provider adapters.

## 11. Replay model

A replay fixture should contain normalized semantics rather than provider-specific wire payloads as primary authority.

```text
fixture_id
input normalized snapshot
objective
candidate set expectations
reduction expectations
expected judgment plan or constraints on it
scripted judgment results
expected bundle validation
expected policy decision
expected fresh-state validation
optional simulated execution/outcome events
```

Required fixture classes:

1. deterministic-only decision with zero JEV questions;
2. one required judgment;
3. multiple independent judgments in one parallel wave;
4. optional judgment cancelled after policy short-circuit;
5. missing required judgment prevents action;
6. invalid judgment type/range is rejected;
7. calibration requirement rejection;
8. stale judgment bundle rejection;
9. selector mode consumed as evidence, not authority;
10. observation-epoch change before execution;
11. pending-intent duplicate suppression;
12. delivery without final effect;
13. successful verified transaction.

## 12. Observability and metrics

Recommended counters:

```text
policy_transactions_total
mechanical_only_transactions_total
judgment_plans_total
judgment_questions_total
judgment_results_answered_total
judgment_results_abstain_total
judgment_results_error_total
judgment_bundles_valid_total
judgment_bundles_partial_total
judgment_bundles_stale_total
selector_judgments_total
deliberative_escalations_total
policy_short_circuit_total
fresh_validation_reject_total
execution_dispatch_total
final_effect_success_total
```

Recommended histograms:

```text
transaction_end_to_end_ms
normalize_ms
reduce_ms
judgment_plan_ms
judgment_question_ms by type
judgment_required_bundle_ms
judgment_full_bundle_ms
policy_ms
fresh_validate_ms
execute_to_accept_ms
execute_to_final_effect_ms
questions_per_plan
parallel_ready_questions_per_wave
```

Useful ratios:

```text
mechanical_resolution_rate
judgment_invocation_rate
selector_mode_rate
optional_cancel_rate
stale_judgment_discard_rate
```

## 13. Versioning

Version contracts independently where practical:

```text
state_schema_version
judgment_question_schema_version
judgment_result_schema_version
judgment_bundle_schema_version
policy_version
semantic_action_schema_version
trace_schema_version
```

Provider changes should not force unrelated schema changes.

Replay fixtures must declare the contract versions they target.

## 14. Suggested implementation order

An AI coding agent should implement in this order unless a concrete constraint requires otherwise:

1. core state/value objects and knowledge-state semantics;
2. candidate generation and deterministic reduction;
3. judgment output contracts and judgment-question schemas;
4. deterministic judgment planner;
5. fake JEV adapter with scripted results;
6. parallel-capable judgment scheduler and bundle assembler;
7. judgment bundle validation;
8. deterministic action policy;
9. fresh-state validator;
10. execution-plan interface and simulated executor;
11. outcome verifier;
12. trace/replay runner;
13. optional real JEV adapter;
14. only then EVE-specific observer or physical executor integration.

This order proves the cognitive architecture before coupling it to volatile client details.

## 15. Things an implementation must not collapse

Do not merge these concepts merely to reduce file count:

```text
raw observation != normalized state
unknown != false
exact fact != probabilistic judgment
probability != arbitrary score
confidence != calibration
parallel evaluation != statistical independence
judgment result != policy decision
policy decision != physical authorization
semantic action != physical step
input delivery != command acceptance
command acceptance != final effect
state epoch != observation epoch
adapter error != semantic abstention
replay success != live-client proof
```

These distinctions are the architecture.
