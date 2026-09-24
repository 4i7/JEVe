# JEVe Detailed Design

This document translates the architecture into implementation-ready contracts without prescribing concrete functions, libraries, or a programming language.

The intended reader is a human or AI coding agent preparing an MVP.

## 1. Design goals

The implementation should make the following properties obvious in code structure:

- deterministic logic is separate from probabilistic reasoning;
- JEV is a replaceable decision provider, not an executor;
- semantic actions are separate from physical operations;
- stale decisions are rejected rather than patched with guesses;
- uncertainty is explicit in state;
- action outcome is verified from observation;
- every decision can be replayed offline;
- provider/client-specific integration details are isolated behind adapters.

## 2. Suggested module boundaries

A language-neutral module layout:

```text
core/
  state/
  candidates/
  reduction/
  routing/
  decisions/
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

An objective should be a declarative goal, not a command sequence.

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

### 3.4 Constraint

```text
Constraint = {
  id: string,
  kind: HARD | SOFT,
  predicate: semantic predicate,
  reason_code: string
}
```

Hard constraints may remove candidates. Soft constraints influence scoring/routing but must not masquerade as hard safety rules.

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

`candidate_id` is unique within a decision request.

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

Candidate generation should be complete with respect to the currently supported action vocabulary. If the generator cannot establish completeness, surface that fact explicitly.

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

### 3.8 Decision request

```text
DecisionRequest = {
  request_id: string,
  snapshot_id: string,
  observation_epoch: integer|string,
  objective: CompactObjective,
  candidates: CompactCandidate[],
  features: DecisionFeatureSet,
  stakes: LOW | MEDIUM | HIGH,
  deadline?: timestamp,
  schema_version: string
}
```

The request intentionally does not need the entire world state. It should contain only decision-relevant normalized features.

### 3.9 Decision response

```text
DecisionResponse = {
  request_id: string,
  selected_candidate_id?: string,
  status: SELECTED | ABSTAIN | NEED_MORE_INFORMATION | ERROR,
  scores?: map<candidate_id, number>,
  confidence?: number,
  rationale_tags?: string[],
  requested_features?: string[],
  adapter_metadata?: map
}
```

`ABSTAIN` is a valid outcome. The system should not force a selection when the model cannot distinguish candidates reliably.

### 3.10 Validated decision

```text
ValidatedDecision = {
  request_id: string,
  selected_action: SemanticAction,
  validation_snapshot_id: string,
  validation_observation_epoch: integer|string,
  validation_reason: string,
  expires_at?: timestamp
}
```

This is the first object eligible for compilation into physical execution.

### 3.11 Execution plan

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

### 3.12 Decision trace

```text
DecisionTrace = {
  trace_id: string,
  snapshot_ref: string,
  candidate_generation: summary,
  reduction: summary,
  routing: summary,
  model_request?: summary,
  model_response?: summary,
  validation: summary,
  execution?: summary,
  outcome?: summary,
  timings: map<string, duration>
}
```

A replay runner should be able to consume the normalized portion without requiring the live client.

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

- do not infer semantics that belong to normalization;
- preserve acquisition time and source identity;
- detect source failure separately from observed absence.

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
- calculate cheap deterministic derived facts;
- establish epoch/freshness metadata;
- reject contradictions rather than picking one silently.

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
- never include an action already forbidden by static capability configuration;
- parameterize by semantic IDs;
- avoid combinatorial explosion by generating only actions relevant to the active objective and current state.

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
2. hard capability availability;
3. hard preconditions;
4. hard safety constraints;
5. objective relevance;
6. exact resource/timer/range constraints;
7. pending-intent conflict;
8. strict dominance;
9. operator policy filters.

Order should be stable so traces remain easy to compare.

Do not use a model inside deterministic reduction.

### Stage E: route

Input:

```text
StateSnapshot + ReductionResult
```

Output:

```text
DETERMINISTIC_SELECT | JEV_FAST | DELIBERATE | OBSERVE_MORE | FAIL_CLOSED
```

Baseline policy:

```text
0 candidates -> OBSERVE_MORE or FAIL_CLOSED
1 candidate  -> DETERMINISTIC_SELECT
2+ candidates:
  stale/insufficient critical evidence -> OBSERVE_MORE
  high novelty -> DELIBERATE
  high stakes + weak expected confidence -> DELIBERATE
  otherwise -> JEV_FAST
```

The exact thresholds are configuration, not architecture.

### Stage F: compact decision context

Before JEV invocation, project the snapshot into candidate-discriminating features.

Good request data:

```text
objective
candidate IDs and semantic descriptions
risk-related normalized features
relevant distances/ranges/timers
relevant known/unknown status
recent decision context when stability matters
```

Bad request data by default:

```text
entire UI tree
screenshots when normalized evidence already exists
unrelated inventory/state
executor-specific coordinates
large history with no decision relevance
```

The compactor should be deterministic and replayable.

### Stage G: JEV decision

The JEV adapter should:

1. serialize the typed request;
2. enforce a deadline;
3. parse the response strictly;
4. reject unknown candidate IDs;
5. return adapter errors as data, not hidden fallback;
6. record latency and adapter metadata;
7. support cancellation when the originating decision becomes stale.

A transport error should not become an arbitrary candidate selection.

### Stage H: post-decision routing

If the JEV response contains scores:

```text
best = top score
second = second-highest score
margin = best - second
```

A configurable policy may:

- accept high-confidence/high-margin low-stakes decisions;
- deliberate on low-margin decisions;
- observe more if critical features are unknown;
- fail closed when the deadline is gone and no safe default exists.

A default action such as `WAIT` should be explicit in the candidate set if it is intended to be selectable.

### Stage I: fresh-state validation

Validation should acquire or reference a sufficiently fresh current snapshot.

Check:

```text
selected candidate still semantically exists
required entities still exist
required preconditions still hold
relevant constraints unchanged
observation epoch compatibility
pending intent compatibility
freshness budget not exceeded
higher-priority inhibit absent
```

If the action requires physical target resolution, physical references should be resolved here or later, never reused blindly from the model request.

### Stage J: compile

The compiler consumes only a validated semantic action plus a current snapshot.

It may return:

```text
COMPILED(plan)
NEEDS_OBSERVATION(feature_set)
UNSUPPORTED(reason)
INHIBITED(reason)
```

It should not silently choose another semantic action when the selected one cannot be compiled.

### Stage K: dispatch and verify

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

The exact number of physical steps is action-specific.

## 5. Fast decision design

The performance objective is to reduce expensive semantic work before optimizing the model call itself.

### 5.1 Candidate-first reasoning

Model complexity increases rapidly when it must both invent and evaluate actions.

Therefore the normal fast path provides a closed set:

```text
{A, B, C}
```

instead of asking:

```text
"What should I do?"
```

This improves latency, parseability, testability, and authority control.

### 5.2 Feature locality

Features should be selected based on the surviving candidate set.

Example:

If all surviving actions concern route choice, combat-fit details that cannot affect route choice should be omitted.

Implementations may define a feature dependency registry:

```text
ActionType -> RequiredFeatureGroups
CandidatePair -> DiscriminatingFeatureGroups
```

This allows deterministic prompt/context minimization.

### 5.3 Caching

Safe cache keys should include the observation epoch and source snapshot identity.

Candidates for caching:

- static domain metadata;
- route graph calculations;
- candidate-independent normalized facts;
- deterministic derived features;
- compact feature projections for an unchanged candidate set.

Do not cache a JEV choice across materially different state without an explicit equivalence proof.

### 5.4 Parallel read-only computation

Independent deterministic feature calculations may run in parallel.

Do not parallelize state-changing execution by default.

### 5.5 Early cancellation

If a newer snapshot invalidates the active decision transaction, cancel outstanding JEV/deliberative work when possible.

The result of cancelled or stale model work may be retained for diagnostics but not executed.

### 5.6 Decision stability

Fast loops can oscillate between semantically equivalent choices.

Use explicit mechanisms such as:

- minimum hold time for a semantic intent where appropriate;
- hysteresis thresholds;
- pending-intent suppression;
- decision-equivalence keys;
- state-change requirements before reconsideration.

These mechanisms belong to deterministic runtime policy, not model prompt wording.

## 6. Semantic resource ownership

A semantic action may claim one or more resources, for example:

```text
navigation
target_selection
engagement
inventory_interaction
```

The MVP may use a simple single-writer map:

```text
resource -> pending_intent_id
```

A new action conflicting with an unresolved owner is rejected, deferred, or deliberately replaces it under explicit policy.

Do not infer cancellation just because a newer decision exists.

## 7. Failure taxonomy

Use typed failure categories so callers do not need to parse error text.

Suggested categories:

```text
OBSERVATION_UNAVAILABLE
OBSERVATION_CONTRADICTORY
STATE_STALE
NO_VALID_CANDIDATE
INSUFFICIENT_EVIDENCE
JEV_TIMEOUT
JEV_TRANSPORT_ERROR
JEV_INVALID_RESPONSE
JEV_ABSTAIN
LOW_DECISION_MARGIN
NOVEL_STATE
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
RETRY_MODEL_ONCE
DELIBERATE
WAIT
FAIL_CLOSED
REQUEST_OPERATOR
```

Avoid generic `retry` without class-specific bounds.

## 8. Configuration

Separate configuration into at least:

```text
DecisionPolicy
SafetyPolicy
FreshnessPolicy
AdapterConfig
TracePolicy
```

Example decision policy fields:

```text
fast_path_max_candidates
low_stakes_confidence_threshold
medium_stakes_confidence_threshold
minimum_margin
novelty_threshold
model_deadline_ms
max_decision_age_ms
```

Do not hard-code policy thresholds deep inside adapters.

## 9. Replay model

Replay is part of the MVP because it lets AI-generated implementations evolve safely without requiring live-client trials for every logic change.

A replay fixture should contain:

```text
fixture_id
input normalized snapshot
objective
expected candidate set or constraints on it
expected route
optional simulated JEV response
expected validation result
optional execution/outcome events
```

Required fixture classes:

1. deterministic single-candidate selection;
2. deterministic elimination with reason codes;
3. no-candidate fail-closed;
4. bounded JEV selection;
5. invalid JEV candidate rejection;
6. JEV abstain;
7. low-margin escalation;
8. stale snapshot rejection;
9. observation-epoch change rejection;
10. pending-intent duplicate suppression;
11. command-delivery without final effect;
12. successful verified action transaction.

## 10. Observability and metrics

Recommended counters:

```text
decisions_total
decisions_deterministic_total
decisions_jev_total
decisions_deliberative_total
decisions_observe_more_total
decisions_fail_closed_total
jev_invalid_response_total
stale_decision_total
validation_reject_total
execution_dispatch_total
final_effect_success_total
```

Recommended histograms:

```text
decision_end_to_end_ms
normalize_ms
reduce_ms
jev_ms
validate_ms
execute_to_accept_ms
execute_to_final_effect_ms
candidate_count_before_reduction
candidate_count_after_reduction
decision_margin
```

The most useful performance ratio is often:

```text
model_invocation_rate = decisions_jev_total / decisions_total
```

A mature implementation may become faster by reducing this ratio while preserving behavior.

## 11. Versioning

Version contracts independently where practical:

```text
state_schema_version
decision_request_schema_version
semantic_action_schema_version
trace_schema_version
```

Adapter changes should not force unrelated schema changes.

A replay fixture must declare the schema version it targets.

## 12. Suggested implementation order

An AI coding agent should implement in this order unless a concrete constraint requires otherwise:

1. core value objects and schema validation;
2. knowledge-state semantics;
3. candidate generator interface;
4. deterministic reducer framework with reason codes;
5. decision router;
6. deterministic/fake JEV adapter;
7. real JEV adapter behind the same interface;
8. fresh-state validator;
9. execution-plan interface and simulated executor;
10. outcome verifier;
11. decision trace/replay runner;
12. only then an EVE-specific observer or physical executor.

This order proves the cognitive architecture before coupling it to volatile client details.

## 13. Things an implementation must not collapse

Do not merge these concepts merely to reduce file count:

```text
raw observation != normalized state
unknown != false
semantic action != physical step
model selection != action authorization
input delivery != command acceptance
command acceptance != final effect
state epoch != observation epoch
confidence != authority
adapter error != semantic abstention
replay success != live-client proof
```

These distinctions are the architecture.
