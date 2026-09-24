# JEVe agent contract

This repository is an architecture-first reference for building a low-latency EVE decision system around JEV.

AI coding agents should preserve the evidence/policy/execution boundaries rather than optimizing for the smallest number of files or the fastest path to a live client.

## Mandatory read order

Before implementing or reviewing a material change, read:

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `docs/JEV_JUDGMENT_MODEL.md`
4. `docs/DETAILED_DESIGN.md`
5. `docs/MVP_PLAN.md`
6. `docs/CLEAN_ROOM.md`
7. the source, tests, and fixtures for the layer being changed

If documents disagree, `docs/ARCHITECTURE.md` owns architectural invariants; `docs/JEV_JUDGMENT_MODEL.md` owns JEV evidence semantics; `docs/DETAILED_DESIGN.md` refines implementation contracts; `docs/MVP_PLAN.md` scopes the first implementation.

## Core invariants

Do not violate these without an explicit architecture change:

1. Exact facts and mechanically decidable branches are resolved deterministically when evidence is sufficient.
2. JEV is primarily a probabilistic semantic evidence generator, not an action authority.
3. JEV questions are decomposed when decomposition creates meaningful reusable evidence or parallelism.
4. Independent read-only JEV judgments should be parallelizable.
5. Judgment output type, semantics, scale, freshness, and correlation are explicit.
6. Numeric scores are not silently treated as calibrated probabilities.
7. Deterministic policy combines exact state, constraints, candidate space, and validated judgments into a semantic branch.
8. Closed-candidate selector mode is optional and its output remains policy evidence.
9. JEV and deliberative adapters never dispatch physical input.
10. `UNKNOWN`, `STALE`, and `TRANSITIONAL` are not equivalent to false.
11. A selected semantic action is revalidated against fresh state before physical execution.
12. Physical references do not survive an incompatible observation-epoch change.
13. Semantic actions and physical execution steps remain separate types/concepts.
14. Input delivery, command acceptance, progress, and final effect are not interchangeable.
15. Equivalent unresolved physical intents are not blindly repeated.
16. Provider-specific JEV and EVE integration details remain behind adapters.
17. Core behavior must be replayable with synthetic fixtures.

## Implementation approach

When modifying code:

- identify the violated or newly required invariant first;
- inspect adjacent cases that exercise the same invariant;
- place the change in the owning architectural layer;
- avoid special-case fixes in adapters when the rule belongs in the core;
- avoid pushing provider/client-specific concepts into generic schemas;
- prefer typed reason/failure codes over parsing log text;
- add or update replay fixtures for subtle state/judgment/policy behavior;
- review the complete path for stale evidence, incompatible scales, duplicate intent, and verification regressions.

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
-> judgment contracts
-> judgment planner
-> fake JEV adapter
-> parallel judgment scheduler
-> judgment bundle validation
-> deterministic policy
-> fresh-state validation
-> simulated execution
-> outcome verification
-> replay/metrics
-> real JEV adapter
-> EVE observation integration
-> physical executor integration
```

A later layer must not bypass an unfinished earlier contract.

## JEV judgment requests

Keep JEV requests compact, typed, and semantic.

Do:

- ask one semantically defined judgment per question unless a provider-native multi-output call preserves equivalent contracts;
- provide only features required by that judgment;
- declare output kind and semantics;
- preserve explicit unknown/freshness state;
- bind results to question, snapshot, and observation epoch;
- declare required vs optional judgments;
- expose dependencies so independent judgments can run concurrently;
- enforce deadlines, cancellation, and strict output parsing.

Do not:

- ask JEV to produce physical executor steps;
- ask one monolithic "what should I do?" question when meaningful decomposed evidence exists;
- treat provider confidence as action authority;
- treat arbitrary numeric scores as probabilities;
- assume parallel judgments are statistically independent;
- manufacture a semantic value after provider error;
- hide an action decision inside an adapter.

## Selector compatibility mode

Closed-candidate selection is allowed when the unresolved semantic property is genuinely a bounded preference.

Represent it as a judgment:

```text
candidate preference / ranking / per-candidate score
```

Then pass the validated result into deterministic policy.

Do not create a separate fast path in which selector output bypasses policy and fresh-state validation.

## Testing expectations

At minimum, changes to the cognition/decision pipeline should preserve fixtures for:

```text
deterministic-only branch with zero JEV questions
single required judgment
multiple independent parallel judgments
partial optional bundle + policy short-circuit
missing required judgment -> no action authority
invalid judgment output type/range
calibration requirement rejection
stale judgment bundle rejection
selector-as-evidence path
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
required exact observations
required probabilistic judgments
policy branch
preconditions
semantic action
physical mapping
command-acceptance evidence
progress evidence if relevant
final-effect evidence
failure/recovery bounds
```

Do not use repeated blind input to compensate for missing observation or verification.

## Performance work

Optimize in this order unless measurement shows otherwise:

1. avoid unnecessary JEV work through exact mechanical reasoning;
2. ask only the semantic judgments required by policy;
3. minimize each judgment's feature slice;
4. parallelize independent read-only judgments;
5. allow policy completion once required evidence is sufficient;
6. cancel stale or no-longer-needed optional work;
7. cache deterministic and judgment-derived state only across proven dependency equivalence;
8. optimize provider transport/runtime latency;
9. only then consider more complex speculative techniques.

Any performance optimization must preserve traceability, judgment semantics, deterministic policy, and fresh-state validation.

## Completion check for a change

Before finalizing a material change, verify:

- the owning invariant is still explicit;
- probabilistic evidence and deterministic policy remain separate;
- judgment scales are not silently conflated;
- independent judgments remain parallelizable where appropriate;
- semantic and physical layers remain separate;
- uncertainty is not silently collapsed;
- stale evidence cannot cross into policy/execution;
- failures have deterministic next-step policy;
- replay coverage exists for the changed behavior;
- no external implementation details leaked into the core;
- documentation is updated if a contract changed.
