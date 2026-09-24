# JEV semantic judgment model

This document defines how JEVe uses JEV as a probabilistic semantic evidence generator.

The core design assumption is that many practical decisions are easier to make when a complex question is decomposed into several small semantic judgments whose outputs can be combined by ordinary deterministic code.

The intended shape is:

```text
structured state
  -> judgment planning
  -> independent semantic questions
  -> parallel JEV evaluation
  -> validated JudgmentBundle
  -> deterministic policy
  -> semantic action or non-action route
```

JEV is not required to own the final branch.

## 1. Why judgment decomposition exists

A single prompt such as:

```text
What should I do now?
```

mixes several jobs:

- deciding which facts matter;
- estimating uncertain semantics;
- comparing alternatives;
- applying policy thresholds;
- selecting an action;
- implicitly deciding whether uncertainty is acceptable.

JEVe separates these jobs.

The deterministic side owns:

```text
known facts
hard constraints
candidate availability
policy thresholds
state-machine legality
freshness rules
physical authority
```

JEV owns only the semantic questions that remain expensive or awkward to encode exactly.

For example:

```text
Is this contact likely hostile?
How risky is route A in the current context?
How risky is route B?
Does the current tactical context support disengagement?
Which target is semantically preferable?
```

These answers may then be composed by deterministic policy.

## 2. Judgment plan

A `JudgmentPlan` describes the semantic evidence required for one policy evaluation.

Illustrative schema:

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

The plan is deterministic output. Given the same normalized state, policy requirements, and configuration, the same plan should be produced.

The plan should contain only questions whose answers can materially affect the current policy branch.

## 3. Judgment question

A `JudgmentQuestion` is a typed semantic query.

```text
JudgmentQuestion = {
  question_id: string,
  judgment_type: string,
  subject: SemanticReference | null,
  feature_slice: map,
  output_contract: JudgmentOutputContract,
  criticality: REQUIRED | OPTIONAL,
  depends_on: string[],
  freshness_dependencies: string[],
  deadline?: timestamp,
  equivalence_key?: string
}
```

Examples:

```text
HOSTILE_PROBABILITY(contact_17)
ROUTE_RISK(route_a)
ROUTE_RISK(route_b)
SHOULD_DISENGAGE(current_context)
TARGET_PREFERENCE(target_set_3)
```

The architecture does not require these exact judgment types. They are examples of the pattern.

## 4. Output contract

Every question declares what kind of answer is valid.

```text
JudgmentOutputContract = {
  value_kind: PROBABILITY | SCORE | BOOLEAN | ENUM | RANKING | DISTRIBUTION,
  range?: [min, max],
  enum_values?: string[],
  semantics: string,
  calibration_requirement?: NONE | DECLARED | CALIBRATED,
  abstention_allowed: boolean
}
```

The `semantics` field matters. It should answer what the value means, not merely how it is encoded.

Examples:

```text
value_kind: PROBABILITY
semantics: "Estimated probability that the observed contact is hostile in the current snapshot context"
range: [0, 1]
```

```text
value_kind: SCORE
semantics: "Relative contextual risk score; only comparable with results from the same judgment type and policy version"
range: [0, 1]
```

These two outputs are not interchangeable even though both use values from zero to one.

## 5. Judgment result

A result is correlated to one question and one originating evidence context.

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
  provider_metadata?: map
}
```

`confidence` is optional and must not be treated as action authority.

Provider-specific metadata may be retained for tracing but must not leak into generic policy unless explicitly normalized into a core semantic field.

## 6. Judgment bundle

A `JudgmentBundle` contains the results available to deterministic policy.

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
  timings: map
}
```

A bundle is not valid merely because all provider calls returned successfully. It must pass semantic validation.

## 7. Parallel execution model

A plan forms a dependency graph.

Questions with no unsatisfied dependencies belong to the same execution wave.

Example:

```text
wave 0:
  hostile_probability
  route_a_risk
  route_b_risk
  disengage_probability

wave 1:
  escape_route_preference
    depends_on: route_a_risk, route_b_risk
```

The preferred path is to avoid wave 1 when deterministic policy can combine wave 0 directly.

Parallelism should be used for independent read-only semantic evaluation, not as permission for parallel physical control.

## 8. Per-question feature projection

Each question should receive the smallest feature slice needed to answer it.

Avoid sending the same full world-state object to every question merely for implementation convenience.

Conceptually:

```text
FeatureProjector(judgment_type, snapshot, subject)
  -> CompactFeatureSlice
```

Examples:

```text
HOSTILE_PROBABILITY
  -> contact behavior, relationship context, local tactical context

ROUTE_RISK
  -> route attributes, known local hazards, objective urgency

SHOULD_DISENGAGE
  -> current damage/resources, threat context, escape availability
```

The actual feature set is domain-specific and must be derived independently by the implementation.

## 9. Partial completion and short-circuiting

Not every planned judgment must always finish.

Policy declares required evidence.

Example:

```text
required:
  hostile_probability
  disengage_probability

optional:
  target_preference
```

If the required set is complete and policy can already determine `RETREAT`, an outstanding optional target-preference judgment may be cancelled.

This yields a useful performance rule:

> **Completion is defined by policy sufficiency, not by waiting for every model call.**

A runtime should still trace cancelled optional work so latency behavior remains observable.

## 10. Freshness dependencies

A judgment is only valid while its semantic dependencies remain compatible.

A conservative MVP may bind every result to the entire snapshot and invalidate the whole bundle on any relevant state change.

A more advanced implementation may declare dependencies:

```text
HOSTILE_PROBABILITY(contact_17)
  depends on:
    contact_17 identity
    contact_17 behavior state
    local tactical context
```

If an unrelated inventory counter changes, that judgment may remain reusable if the implementation can prove dependency equivalence.

An observation-epoch change should normally invalidate all physical-context-dependent judgments unless their contracts explicitly state otherwise.

## 11. Deterministic policy composition

The deterministic policy consumes exact facts and validated judgments.

Example only:

```text
if ship_escape_required_by_hard_rule:
    return RETREAT

if hostile_probability is missing:
    return OBSERVE_MORE

if hostile_probability >= configured_hostile_threshold
   and disengage_probability >= configured_disengage_threshold:
    return RETREAT

if route_a_risk and route_b_risk are comparable:
    return lower_risk_allowed_route

return WAIT
```

The thresholds above are configuration, not universal truths.

The important property is that the action branch is deterministic and replayable once its inputs are fixed.

## 12. Scores vs probabilities

JEVe must not convert all numeric model output into probability language.

A `SCORE` may be useful when only relative ordering matters.

A `PROBABILITY` is appropriate only when the adapter/provider contract supports that interpretation and the policy accepts its calibration status.

Policy may define rules such as:

```text
LOW consequence:
  uncalibrated score may be sufficient for ranking

HIGH consequence:
  probability-like evidence must satisfy stronger calibration / margin / corroboration requirements
```

These are deployment policies, not architecture constants.

## 13. Confidence

Confidence is metadata about a judgment, not a second action selector.

A policy may use confidence to:

- request more observation;
- escalate to deliberation;
- demand corroborating judgments;
- refuse a high-consequence action.

A policy must not treat provider confidence as proof that the underlying semantic claim is true.

## 14. Correlated questions

Decomposition should not pretend correlated questions are independent.

Examples of possible correlation:

```text
route_a_risk and route_b_risk share the same local threat context
hostile_probability and disengage_probability may use overlapping evidence
```

Correlation does not forbid parallel execution, but it affects how policy interprets combined evidence.

Do not multiply or otherwise combine probability-like outputs as if they were independent unless the statistical assumption is explicitly justified.

## 15. Contradictory judgments

A bundle may be internally surprising or contradictory.

Example:

```text
hostile_probability = 0.95
disengage_probability = 0.05
```

This is not automatically an error: the current state might support fighting despite hostility.

Contradiction validation should therefore be contract-specific, not based on intuitive expectations.

When a combination violates an explicit semantic invariant, policy should route to one of:

```text
OBSERVE_MORE
REASK_SELECTED_JUDGMENTS
DELIBERATE
FAIL_CLOSED
```

## 16. Selector mode as a judgment type

Closed-candidate selection remains useful when the unresolved semantic quantity is directly a preference among a bounded set.

Represent it as evidence:

```text
CandidatePreferenceJudgment = {
  candidates: [A, B, C],
  output: ranking | selected_candidate | per_candidate_scores
}
```

The deterministic policy then decides whether that preference is acceptable.

This preserves one uniform rule:

```text
JEV output -> validated semantic evidence -> deterministic policy
```

rather than creating a separate authority path.

## 17. Deliberative escalation

The fast judgment model is not intended to solve every cognitive problem.

Escalate when:

- the required judgment schema does not exist;
- candidate generation itself is uncertain;
- objectives conflict in a way not represented by policy;
- the state is novel enough that configured judgment semantics are unreliable;
- policy cannot resolve contradictory evidence;
- consequences exceed the accepted evidence quality.

The deliberative result must still return through an explicit deterministic authority boundary.

## 18. Caching

Good cache candidates include:

```text
static metadata
deterministic derived features
feature projections
judgments whose declared dependencies are unchanged
```

A safe judgment cache key may include:

```text
judgment_type
subject semantic identity
normalized feature-equivalence key
policy/schema version
provider/model version when semantically relevant
```

Do not cache merely by prompt text or wall-clock proximity.

## 19. Replay

Replay fixtures should store normalized semantics, not provider-specific wire payloads as the primary test authority.

A judgment replay fixture may contain:

```text
snapshot
objective
candidate set
judgment plan
scripted judgment results
expected bundle validation
expected policy decision
```

This lets the same core policy be tested with:

- fake JEV output;
- recorded normalized output;
- alternative provider adapters.

## 20. Required MVP cases

The first implementation should demonstrate at least:

```text
mechanical-only decision with zero JEV questions
one judgment required
multiple independent judgments run in parallel
partial optional bundle with deterministic short-circuit
required judgment missing -> no action authority
invalid output type/range rejection
uncalibrated score rejected by a policy that requires calibrated probability
stale judgment bundle rejection
selector judgment used only as policy evidence
high-stakes bundle escalated to deliberation
```

## 21. Metrics

Recommended counters:

```text
judgment_plans_total
judgment_questions_total
judgment_results_answered_total
judgment_results_abstain_total
judgment_results_error_total
judgment_bundles_valid_total
judgment_bundles_partial_total
judgment_bundles_stale_total
policy_short_circuit_total
selector_judgments_total
```

Recommended latency metrics:

```text
judgment_plan_ms
judgment_question_ms by type
judgment_bundle_required_completion_ms
judgment_bundle_full_completion_ms
policy_ms
```

Recommended structure metrics:

```text
questions_per_plan
parallel_ready_questions_per_wave
required_question_fraction
optional_cancel_fraction
```

## 22. Compatibility rule

An implementation is JEVe-compatible if it preserves the authority and evidence boundaries even when its exact provider API differs.

Provider-native batching, multi-output calls, local inference, remote inference, or multiple simultaneous requests are all implementation choices.

The core must still be able to explain:

```text
what semantic question was asked
what output semantics were expected
which state/evidence it depended on
what result was returned
whether it was valid and fresh
how deterministic policy used it
what action or non-action branch followed
```
