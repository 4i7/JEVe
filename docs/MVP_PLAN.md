# JEVe MVP plan

This document defines the smallest implementation that demonstrates JEVe's architecture without requiring a production EVE client integration.

The MVP is successful when the decision pipeline can be exercised end to end with synthetic observations, a fake JEV adapter, deterministic action policy, a simulated executor, and replayable traces.

## 1. MVP question

The MVP should answer one question convincingly:

> Can a system resolve exact choices mechanically, ask JEV only for the unresolved semantic evidence, evaluate independent judgments concurrently, combine those judgments through deterministic policy, reject stale/invalid evidence, and verify the resulting semantic outcome through one common pipeline?

If yes, the architecture is viable enough to expand.

## 2. Required capabilities

### A. Normalized immutable snapshots

A fixture or observer adapter can produce a `StateSnapshot` with:

```text
snapshot_id
observation_epoch
state_epoch
observed_at
facts with explicit knowledge state
objectives
constraints
```

Acceptance:

- snapshots are treated as immutable;
- unknown/stale/transitional values remain distinguishable;
- an epoch change can be represented explicitly.

### B. Candidate generation

For at least one small example domain, generate semantic candidates from state and objective.

Recommended demonstration vocabulary:

```text
WAIT
CONTINUE_ROUTE(route_id)
TAKE_ALTERNATE_ROUTE(route_id)
RETREAT(destination_id)
```

Acceptance:

- no physical/UI references appear in candidates;
- candidate IDs are stable within one policy transaction;
- unsupported actions are not generated.

### C. Deterministic reduction

Implement a reducer chain that rejects candidates with typed reason codes.

Minimum demonstration rules:

```text
invalid precondition
hard constraint violation
unavailable resource/action
strictly dominated exact option
pending-intent conflict
```

Acceptance:

- a fully decidable result bypasses JEV;
- a zero-candidate result fails closed or requests observation;
- every elimination is traceable.

### D. Judgment planning

Implement a deterministic `JudgmentPlanner` that turns unresolved semantic dimensions into typed questions.

For the demonstration domain, support at least:

```text
ROUTE_RISK(route_id) -> SCORE or PROBABILITY-like configured contract
SHOULD_DISENGAGE(context) -> PROBABILITY or SCORE
```

The exact semantics must be declared by the output contract.

Acceptance:

- no question asks for physical input;
- each question has a stable `question_id`;
- each question declares its output type and semantics;
- required and optional questions are distinguished;
- dependencies are explicit.

### E. Parallel-capable JEV adapter boundary

Implement a JEV adapter interface plus a fake adapter.

The fake adapter should support scripted results for:

```text
answered probability/score
boolean or enum result
abstain
need more information
invalid type/range
timeout/error
calibrated vs uncalibrated metadata
```

The runtime must be able to execute multiple independent questions concurrently or simulate that concurrency deterministically in tests.

Acceptance:

- independent questions are scheduled in the same wave;
- provider failure does not synthesize a judgment value;
- the adapter can be swapped without modifying action policy.

### F. Judgment bundle validation

Assemble results into a `JudgmentBundle`.

Minimum checks:

```text
question/result correlation
snapshot/epoch binding
value kind and range
required result presence
calibration requirement
freshness
```

Acceptance:

- missing required judgment prevents action authority;
- invalid numeric semantics are rejected;
- optional missing judgments may be accepted only when policy allows it;
- stale bundles do not enter policy as current evidence.

### G. Deterministic action policy

Implement a deterministic policy consuming:

```text
fresh normalized state
hard constraints
surviving semantic candidates
validated judgment bundle
configuration
```

and returning one of:

```text
SELECTED
OBSERVE_MORE
DELIBERATE
WAIT
FAIL_CLOSED
```

Acceptance:

- identical inputs/configuration produce the same branch;
- JEV output alone does not directly dispatch or authorize physical action;
- hard constraints dominate model evidence;
- policy can decline to act when evidence is insufficient.

### H. Optional selector judgment

Support one compatibility scenario where JEV returns a bounded candidate preference or ranking.

Acceptance:

- the selector result is represented as semantic evidence;
- deterministic policy still owns acceptance/rejection and final branch;
- an out-of-set candidate is rejected.

### I. Fresh-state validation

Before compilation, validate the selected semantic action against a fresh snapshot.

Minimum checks:

```text
selected candidate still exists
preconditions still hold
observation epoch compatible
state freshness acceptable
no conflicting pending intent
```

Acceptance:

- an epoch change rejects an otherwise valid policy decision;
- a vanished target/precondition rejects execution;
- validation failure returns to observation or fail-closed policy.

### J. Simulated action compilation and execution

Implement a test action compiler and simulated executor.

Acceptance:

- compilation cannot silently change the semantic action;
- physical plan steps are distinct from semantic actions;
- delivery can occur without implying success.

### K. Outcome verification

Demonstrate the difference between:

```text
DELIVERED
COMMAND_ACCEPTED
PROGRESSING
FINAL_EFFECT
```

Acceptance:

- final success requires the configured semantic final-effect predicate;
- elapsed time alone cannot promote a stalled action to success.

### L. Decision trace and replay

Persist or emit a structured trace.

Acceptance:

- the trace records mechanical reduction, judgment plan, per-question results, bundle validation, policy branch, fresh-state validation, and outcome;
- scripted replay produces the same policy result;
- replay does not require the live EVE client.

## 3. Suggested implementation skeleton

```text
README.md
AGENTS.md
docs/
  ARCHITECTURE.md
  JEV_JUDGMENT_MODEL.md
  DETAILED_DESIGN.md
  MVP_PLAN.md
  CLEAN_ROOM.md

src/
  core/
    state
    candidates
    reduction
    judgments
    policy
    validation
    actions
    verification
    traces
  adapters/
    jev
    observer
    executor
  runtime/
    decision-loop
    judgment-scheduler
    pending-intents
  replay/
    runner

fixtures/
  deterministic-only
  single-judgment
  parallel-judgment-bundle
  optional-short-circuit
  missing-required-judgment
  invalid-judgment-output
  calibration-rejection
  stale-bundle
  selector-evidence
  epoch-change
  delivered-not-complete
  verified-complete

tests/
```

Do not create empty architectural layers merely to match this tree. Add a module when its contract is actually implemented.

## 4. Recommended first scenario

Use a deliberately small synthetic navigation/risk scenario.

Example exact state:

```text
objective: reach destination while respecting configured risk ceiling
route A: reachable, shorter
route B: reachable, longer
WAIT: available
RETREAT: available
hard constraints: none violated
```

Exact code can establish reachability, length, and candidate legality.

Semantic uncertainty remains:

```text
Q1: contextual risk of route A
Q2: contextual risk of route B
Q3: whether current context supports disengagement
```

`Q1`, `Q2`, and `Q3` should be independent enough for the demonstration to run in one judgment wave.

A deterministic policy then combines the results. For example, under an explicitly configured demonstration policy:

```text
if disengage judgment exceeds threshold:
    RETREAT
else if route A and B risk values are comparable:
    choose lower-risk allowed route
else:
    WAIT / OBSERVE_MORE
```

The thresholds are test configuration, not architectural constants.

A second scenario must be entirely deterministic so JEV call count is zero.

## 5. Required replay fixtures

| Fixture | Expected property |
|---|---|
| deterministic-only | exact policy branch; JEV question count = 0 |
| single-judgment | one required semantic judgment drives policy input |
| parallel-bundle | 2+ independent questions scheduled in one wave |
| optional-short-circuit | policy completes after required results; optional work may cancel |
| required-missing | no action authority when required evidence is absent |
| invalid-output | wrong result type/range rejected |
| calibration-rejection | policy requiring calibrated evidence rejects insufficient metadata |
| stale-bundle | stale semantic evidence discarded |
| selector-evidence | bounded selector output enters policy as evidence only |
| epoch-change | physical execution prohibited until re-resolution |
| duplicate-pending-intent | duplicate physical action suppressed |
| delivered-not-complete | delivery not counted as final effect |
| verified-final-effect | success only from observed semantic outcome |

## 6. Minimum metrics

Track:

```text
policy transactions
mechanical-only transactions
judgment plans
judgment question count
questions per plan
parallel-ready questions per wave
judgment answer/abstain/error count
required-bundle wall-clock latency
full-bundle wall-clock latency
policy short-circuits
selector-mode usage
stale judgment discards
fresh validation rejections
verified final effects
end-to-end decision latency
```

Useful ratios:

```text
mechanical_resolution_rate = mechanical_only / policy_transactions
judgment_invocation_rate = transactions_with_judgments / policy_transactions
selector_mode_rate = selector_transactions / transactions_with_judgments
optional_cancel_rate = cancelled_optional_questions / optional_questions_started
```

For a stable domain, maturation should often increase mechanical resolution and reduce unnecessary semantic work.

## 7. Performance targets

Do not hard-code universal millisecond targets before measuring the chosen runtime and JEV provider.

Define budgets per deployment:

```text
observation_budget
mechanical_prepass_budget
judgment_plan_budget
required_bundle_budget
policy_budget
fresh_validation_budget
execution_start_budget
```

The architectural performance acceptance is initially qualitative:

1. exact choices avoid JEV latency entirely;
2. only unresolved semantic questions invoke JEV;
3. independent questions are parallelizable;
4. each question receives compact normalized context;
5. policy may complete when required evidence is sufficient without waiting for optional work;
6. stale JEV work can be cancelled/discarded;
7. model latency does not block passive observation;
8. physical execution is not repeated simply because cognition runs faster.

After measurement, convert these into numeric SLOs.

## 8. What not to build in the MVP

Do not expand the first implementation into:

- a complete EVE UI parser;
- a complete combat system;
- generalized screen automation;
- autonomous long-horizon planning;
- automatic rule learning/promotion;
- statistical probability fusion without justified assumptions;
- multi-client parallel physical control;
- a large plugin framework;
- a database unless traces actually require one;
- provider-specific semantics leaked into the core.

## 9. AI coding-agent workflow

Recommended order:

```text
Increment 1: core schemas + knowledge-state tests
Increment 2: candidate/reduction framework + reason-code fixtures
Increment 3: judgment contracts + deterministic judgment planner
Increment 4: fake JEV adapter + parallel-capable scheduler
Increment 5: judgment bundle validation + calibration/freshness rules
Increment 6: deterministic action policy + selector-as-evidence compatibility
Increment 7: fresh-state validation
Increment 8: simulated compiler/executor/verifier
Increment 9: trace + replay runner + metrics
Increment 10: optional real JEV adapter
Increment 11: optional EVE observer integration
Increment 12: optional real executor integration
```

For each increment, require:

- invariant being implemented;
- changed contracts;
- tests/fixtures;
- failure modes;
- whether any external assumption was introduced;
- architecture review for accidental coupling.

## 10. Definition of MVP complete

The MVP is complete when all of the following are true:

- a deterministic scenario completes without JEV;
- an ambiguous scenario produces typed semantic judgment questions rather than one mandatory action-selection prompt;
- 2+ independent questions can be evaluated in parallel;
- invalid, stale, missing-required, or semantically incompatible judgment output cannot create action authority;
- deterministic policy combines judgments with exact state and constraints;
- selector mode, when used, remains evidence rather than direct execution authority;
- policy can return observe-more/deliberate/wait/fail-closed instead of forcing an action;
- a decision becomes unusable after an incompatible observation-epoch change;
- semantic action compilation is visibly separate from policy and JEV;
- delivery, acceptance, progress, and final effect are not conflated;
- replay fixtures reproduce policy behavior offline;
- the core has no dependency on a particular UI automation implementation;
- the core has no dependency on another repository's source-specific concepts;
- an AI can read the repository documents and identify the next implementation layer without inventing missing architecture.

At that point, choose further work from measured bottlenecks and the intended EVE integration rather than adding abstraction for its own sake.
