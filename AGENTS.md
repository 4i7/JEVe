# JEVe agent contract

This repository is an architecture-first reference for building a low-latency EVE decision system around JEV.

AI coding agents should preserve the decision/execution boundaries rather than optimizing for the smallest number of files or the fastest path to a live client.

## Mandatory read order

Before implementing or reviewing a material change, read:

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `docs/DETAILED_DESIGN.md`
4. `docs/MVP_PLAN.md`
5. `docs/CLEAN_ROOM.md`
6. the source, tests, and fixtures for the layer being changed

If documents disagree, `docs/ARCHITECTURE.md` owns architectural invariants; `docs/DETAILED_DESIGN.md` refines implementation contracts; `docs/MVP_PLAN.md` scopes the first implementation.

## Core invariants

Do not violate these without an explicit architecture change:

1. Deterministic decisions are resolved mechanically when evidence is sufficient.
2. JEV normally chooses only from a closed semantic candidate set.
3. JEV does not dispatch physical input.
4. `UNKNOWN`, `STALE`, and `TRANSITIONAL` are not equivalent to false.
5. A selected semantic action is revalidated against fresh state before physical execution.
6. Physical references do not survive an incompatible observation-epoch change.
7. Semantic actions and physical execution steps remain separate types/concepts.
8. Input delivery, command acceptance, progress, and final effect are not interchangeable.
9. Equivalent unresolved physical intents are not blindly repeated.
10. Provider-specific JEV and EVE integration details remain behind adapters.
11. Core behavior must be replayable with synthetic fixtures.

## Implementation approach

When modifying code:

- identify the violated or newly required invariant first;
- inspect adjacent cases that exercise the same invariant;
- place the change in the owning architectural layer;
- avoid special-case fixes in adapters when the rule belongs in the core;
- avoid pushing provider/client-specific concepts into generic schemas;
- prefer typed reason/failure codes over parsing log text;
- add or update a replay fixture for subtle state/decision behavior;
- review the complete decision path for stale-state, duplicate-intent, and verification regressions.

Do not perform broad refactors merely to make a small change look cleaner.

## Clean-room rule

Do not reconstruct another repository's source code, naming, file structure, constants, or private protocols in this repository.

When an external implementation suggests a useful behavior, restate the behavior as an independent semantic contract and implement it from public documentation, direct observation, controlled experiments, or synthetic fixtures. Follow `docs/CLEAN_ROOM.md`.

## AI expansion strategy

Prefer bounded increments in this order:

```text
state/schema
-> candidate generation
-> deterministic reduction
-> routing
-> fake JEV adapter
-> real JEV adapter
-> fresh-state validation
-> simulated execution
-> outcome verification
-> replay/metrics
-> EVE observation integration
-> physical executor integration
```

A later layer should not be used to bypass an unfinished earlier contract.

## JEV requests

Keep JEV requests compact and structured.

Do:

- provide the objective;
- provide closed candidate IDs and semantic descriptions;
- provide only candidate-discriminating normalized features;
- preserve explicit unknown/freshness state;
- bind response to request/snapshot identity;
- enforce deadlines and strict output parsing.

Do not:

- send raw physical controls as actions;
- ask JEV to invent executor steps on the normal fast path;
- treat confidence as authority;
- accept a candidate ID that was not requested;
- convert provider error into a guessed action.

## Testing expectations

At minimum, changes to the decision pipeline should preserve fixtures for:

```text
deterministic single-candidate bypass
zero-candidate fail-closed
bounded JEV choice
invalid JEV candidate rejection
JEV abstention
low-margin escalation
stale-decision rejection
observation-epoch invalidation
pending-intent duplicate suppression
delivery without final effect
verified final effect
```

A real client is not required to validate core logic.

## External-state changes

If a future implementation controls the EVE client, model each consequential operation semantically before implementing physical input.

Document:

```text
semantic objective
required evidence
preconditions
action
physical mapping
command-acceptance evidence
progress evidence if relevant
final-effect evidence
failure/recovery bounds
```

Do not use repeated blind input to compensate for missing observation or verification.

## Performance work

Optimize in this order unless measurement shows otherwise:

1. avoid unnecessary JEV calls through deterministic reduction;
2. minimize JEV context to discriminating features;
3. cancel stale work;
4. parallelize independent read-only computation;
5. cache deterministic derived state within safe snapshot/epoch boundaries;
6. optimize provider transport/runtime latency;
7. only then consider more complex speculative techniques.

Any performance optimization must preserve decision traceability and fresh-state validation.

## Completion check for a change

Before finalizing a material change, verify:

- the owning invariant is still explicit;
- semantic and physical layers remain separate;
- uncertainty is not silently collapsed;
- stale state cannot cross into execution;
- failures have deterministic next-step policy;
- replay coverage exists for the changed behavior;
- no external implementation details leaked into the core;
- documentation is updated if a contract changed.
