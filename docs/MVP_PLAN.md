# JEVe MVP plan

This document defines the smallest implementation that demonstrates JEVe's architecture without requiring a production EVE client integration.

The MVP is successful when the decision pipeline can be exercised end to end with synthetic observations, a fake or real JEV adapter, a simulated executor, and replayable traces.

## 1. MVP question

The MVP should answer one question convincingly:

> Can a system resolve mechanically decidable choices without a model, invoke JEV only for bounded semantic ambiguity, reject stale/invalid decisions, and verify a semantic outcome through one common pipeline?

If yes, the architecture is viable enough to expand.

## 2. Required capabilities

The MVP must implement these capabilities at contract level:

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

This is only a demonstration domain. It should not become a hard-coded architectural dependency.

Acceptance:

- no physical/UI references appear in candidates;
- candidate IDs are stable within one request;
- unsupported actions are not generated.

### C. Deterministic reduction

Implement a reducer chain that can reject candidates with typed reason codes.

Minimum rules for the demonstration:

```text
invalid precondition
hard constraint violation
unavailable resource/action
strictly dominated option
pending-intent conflict
```

Acceptance:

- a one-candidate result bypasses JEV;
- a zero-candidate result fails closed or requests observation;
- every elimination is traceable.

### D. Decision routing

Implement a deterministic router with at least:

```text
DETERMINISTIC_SELECT
JEV_FAST
DELIBERATE
OBSERVE_MORE
FAIL_CLOSED
```

The MVP may stub `DELIBERATE`, but the route must exist.

Acceptance:

- one candidate routes to deterministic selection;
- multiple low-stakes candidates can route to JEV;
- stale/critical-unknown state can route to observation rather than JEV;
- configured high-stakes/novel cases can route away from the fast path.

### E. JEV adapter boundary

Implement an adapter interface plus a fake adapter.

The fake adapter should support scripted results:

```text
valid selection
abstain
invalid candidate ID
timeout/error
scored low-margin selection
scored high-margin selection
```

A real JEV provider adapter may be added, but it is not required for the architecture MVP.

Acceptance:

- invalid output cannot cross validation;
- provider failure does not select an arbitrary fallback candidate;
- the adapter can be swapped without modifying core decision logic.

### F. Fresh-state validation

Before compilation, validate the selected semantic action against a fresh snapshot.

Minimum checks:

```text
request/response correlation
candidate membership
precondition still true
observation epoch compatible
state freshness acceptable
no conflicting pending intent
```

Acceptance:

- an epoch change rejects an otherwise valid model choice;
- a vanished target/precondition rejects execution;
- validation failure returns to observation or fail-closed policy.

### G. Simulated action compilation and execution

Implement a test action compiler and simulated executor.

The compiler turns a semantic action into a synthetic `ExecutionPlan`; the executor applies controlled simulated state transitions.

Acceptance:

- compilation cannot silently change the selected semantic action;
- plan steps are distinct from semantic actions;
- an action can be delivered without immediately implying success.

### H. Outcome verification

Demonstrate the difference between:

```text
DELIVERED
COMMAND_ACCEPTED
PROGRESSING
FINAL_EFFECT
```

Not every example needs every intermediate state, but at least one fixture should distinguish delivery from final effect.

Acceptance:

- final success requires the configured semantic final-effect predicate;
- a stalled or unaccepted action does not become success due to elapsed time alone.

### I. Decision trace and replay

Persist or emit a structured trace that can be replayed offline.

Acceptance:

- the trace records candidate generation, reduction, routing, optional JEV result, validation, and outcome;
- the same fixture with a scripted adapter produces the same semantic result;
- replay does not require the live EVE client.

## 3. Suggested implementation skeleton

A minimal repository after implementation might look like:

```text
README.md
AGENTS.md
docs/
  ARCHITECTURE.md
  DETAILED_DESIGN.md
  MVP_PLAN.md
  CLEAN_ROOM.md

src/
  core/
    state
    candidates
    reduction
    routing
    decisions
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
    pending-intents
  replay/
    runner

fixtures/
  deterministic-single-candidate
  jev-bounded-choice
  jev-invalid-response
  jev-low-margin
  stale-decision
  epoch-change
  pending-intent
  delivered-not-complete
  verified-complete

tests/
```

Do not create empty architectural layers merely to match this tree. Add a module when its contract is actually implemented.

## 4. Recommended first scenario

Use a deliberately small synthetic navigation-choice scenario.

Example state:

```text
objective: reach destination while respecting configured risk ceiling
current_state: stable
route A: available, shorter, risk feature uncertain/high
route B: available, longer, risk feature known/lower
WAIT: available
```

The point is not to model EVE routing perfectly. The point is to exercise all three kinds of reasoning:

- deterministic removal of impossible choices;
- JEV comparison of bounded semantic alternatives when risk interpretation remains ambiguous;
- fresh-state rejection if the world changes before execution.

A second scenario should be entirely deterministic so the model is demonstrably bypassed.

## 5. Required replay fixtures

The initial suite should cover at least:

| Fixture | Expected property |
|---|---|
| deterministic-single | one surviving candidate; JEV call count = 0 |
| no-valid-candidate | no improvisation; fail closed/observe more |
| bounded-jev-choice | selected ID belongs to request candidate set |
| invalid-jev-id | response rejected |
| jev-abstain | no forced physical action |
| low-margin | configured escalation path used |
| stale-before-validation | decision discarded |
| epoch-change | physical execution prohibited until re-resolution |
| duplicate-pending-intent | duplicate physical action suppressed |
| delivered-not-complete | delivery not counted as final effect |
| verified-final-effect | transaction reaches success only from observed semantic outcome |

## 6. Minimum metrics

Even the MVP should expose enough metrics to answer whether the architecture is becoming faster.

Track:

```text
total decisions
mechanically resolved decisions
JEV-invoked decisions
deliberative/escalated decisions
failed-closed decisions
candidate count before/after reduction
JEV latency
end-to-end decision latency
stale decisions discarded
validation rejections
verified final effects
```

Two particularly useful ratios:

```text
mechanical_resolution_rate = deterministic_decisions / total_decisions
model_invocation_rate = JEV_decisions / total_decisions
```

For a stable domain, successful maturation should often increase the first ratio and reduce unnecessary model calls.

## 7. Performance targets

Do not hard-code universal millisecond targets before measuring the chosen runtime and JEV provider.

Instead define budgets per deployment:

```text
observation_budget
mechanical_decision_budget
JEV_fast_path_budget
fresh_validation_budget
execution_start_budget
```

The architectural performance acceptance is qualitative at first:

1. deterministic choices avoid JEV latency entirely;
2. JEV requests contain only compact normalized decision context;
3. stale JEV work can be cancelled/discarded;
4. model latency does not block passive observation;
5. physical execution is not repeated simply because cognition runs faster.

After measurement, convert these into explicit numeric SLOs.

## 8. What not to build in the MVP

Do not expand the first implementation into:

- a complete EVE UI parser;
- a complete combat system;
- generalized screen automation;
- autonomous long-horizon planning;
- automatic rule learning/promotion;
- multi-client parallel physical control;
- a large plugin framework;
- a database unless traces actually require one;
- provider-specific features leaked into the core.

These can be added after the architecture is proven.

## 9. AI coding-agent workflow

When asking an AI to turn this design into code, give it a bounded increment.

Recommended order:

```text
Increment 1: core schemas + knowledge-state tests
Increment 2: candidate/reduction framework + reason-code fixtures
Increment 3: router + fake JEV adapter
Increment 4: decision response validation + freshness/epoch validation
Increment 5: simulated compiler/executor/verifier
Increment 6: trace + replay runner
Increment 7: optional real JEV adapter
Increment 8: optional EVE observer integration
Increment 9: optional real executor integration
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

- a deterministic scenario completes without invoking JEV;
- an ambiguous scenario invokes JEV with a closed candidate set;
- invalid or out-of-set JEV output is rejected;
- low-confidence/low-margin or configured high-risk output can be escalated;
- a decision becomes unusable after an incompatible observation epoch change;
- semantic action compilation is visibly separate from model selection;
- delivery, acceptance, progress, and final effect are not conflated;
- replay fixtures reproduce the decision logic offline;
- the core has no dependency on a particular UI automation implementation;
- the core has no dependency on another repository's source-specific concepts;
- an AI can read the repository documents and identify the next implementation layer without inventing missing architecture.

At that point, the next work should be selected based on measured bottlenecks and the intended EVE integration, not by adding architecture for its own sake.
