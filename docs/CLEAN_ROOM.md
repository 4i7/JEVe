# Clean-room implementation policy

JEVe is designed so that integrations can be implemented independently without copying code, identifiers, file layouts, private assumptions, or undocumented behavior from another repository.

This document defines the clean-room boundary for contributors and AI coding agents.

## 1. Goal

The goal is reproducibility:

> A competent engineer should be able to implement JEVe from this repository, public documentation, and their own observations without access to another implementation's source code.

That requirement improves portability and prevents architectural coupling to accidental details.

## 2. What may be reused conceptually

The following ideas are suitable for independent reimplementation:

- separation of observation, judgment, deterministic policy, validation, and execution;
- decomposed semantic questions;
- concurrent evaluation of independent read-only judgments;
- typed probabilistic/score/enum/ranking evidence;
- explicit unknown/stale/transitional state;
- semantic actions instead of raw input commands;
- fresh-state validation before execution;
- command-acceptance/progress/final-effect verification;
- replay-based testing;
- deterministic reduction before probabilistic reasoning;
- adapter boundaries around volatile integrations.

These concepts must be expressed using JEVe's own contracts and terminology.

## 3. What must not be copied from another implementation

Do not copy or mechanically translate:

- source files or source fragments;
- class, function, namespace, module, or private protocol names that are implementation-specific;
- internal file/directory layout merely to preserve structural similarity;
- magic constants or thresholds without independently establishing their meaning;
- serialized private schemas;
- undocumented parser assumptions;
- UI coordinates or node paths obtained from another codebase;
- private fixtures or diagnostic captures;
- comments or prose whose purpose is to reconstruct source logic line by line;
- commit history as an implementation recipe.

If a value or behavior is needed, derive it independently from a public contract, direct observation, synthetic testing, or explicit configuration.

## 4. Architecture vs integration

Stable core:

```text
normalized state
candidate generation
mechanical reduction
judgment planning
JudgmentQuestion / JudgmentResult / JudgmentBundle
deterministic action policy
fresh-state validation
semantic action
execution-plan contract
outcome verification
trace/replay model
```

External integration:

```text
how EVE state is observed
how semantic entities are identified
how JEV is invoked or batched
how provider-specific outputs are normalized into judgment contracts
how physical input is delivered
how final effects are observed on a real client
```

The core should not need implementation details from the integration layer.

## 5. Source-of-truth hierarchy for a clean implementation

When implementing an integration, prefer evidence in this order:

1. documented public interface or protocol;
2. stable behavior directly observed by the implementer;
3. controlled experiments created specifically for JEVe;
4. clearly labeled inference with fail-closed handling;
5. unsupported assumptions only as temporary TODOs, never hidden execution premises.

An inference should remain labeled as inference in design notes and tests until independently established.

## 6. Interface-first workflow

For any integration that may also exist elsewhere, define the JEVe-facing contract first.

Example:

```text
ObserverAdapter
  -> RawObservation

JEVAdapter
  -> JudgmentQuestion or provider-native batch
  -> JudgmentResult[]

ExecutorAdapter
  -> ExecutionPlan
  -> DeliveryResult
```

The exact function names are illustrative. The important point is that the contract is written from JEVe requirements rather than inferred from another repository's implementation shape.

Only after the contract is stable should an integration be written.

## 7. Behavioral specification method

If another system demonstrates a useful capability, do not inspect its internals as the implementation guide. Restate the required behavior independently.

Bad specification:

```text
Implement the same resolver, state machine, thresholds, and model pipeline.
```

Good specification:

```text
Given normalized semantic state, derive the set of judgment questions required by current deterministic policy; evaluate independent questions concurrently; reject results that do not satisfy their declared type/freshness contract; and allow only deterministic policy to produce a semantic action.
```

The second form can be implemented many ways and exposes the actual invariant.

## 8. Clean-room evidence ledger

When an integration contains non-obvious domain knowledge, keep a short evidence ledger in its design notes.

Suggested format:

```text
Claim:
  What behavior or fact is being relied on?

Source class:
  PUBLIC_DOCUMENTATION | DIRECT_OBSERVATION | CONTROLLED_EXPERIMENT | INFERENCE

Evidence:
  Link, reproducible steps, or fixture identifier.

Scope:
  Where is the claim known to hold?

Unknowns:
  What has not been established?

Execution consequence:
  What happens if the claim cannot be established at runtime?
```

For public repositories, do not commit private account data or raw captures containing sensitive information.

## 9. EVE-specific integration guidance

An EVE integration should model the human-visible semantic operation before choosing the physical mechanism.

For each state-changing operation, document:

```text
semantic objective
required exact observations
semantic judgments required by policy
judgment output semantics
policy branch
preconditions
semantic action
physical mapping strategy
command-acceptance signal, if observable
progress signal, if applicable
final-effect signal
failure modes
bounded recovery
```

Do not start with "what coordinate should be clicked?" Start with "what semantic operation is required, what is known exactly, what remains judgmental, and what evidence proves the result?"

A client UI path is implementation detail and should be resolved from fresh observation as late as possible.

## 10. JEV provider clean-room boundary

The core must not assume undocumented details of one JEV transport/provider.

Provider-specific code may know:

- authentication/configuration;
- request serialization;
- provider-native batching or multi-output features;
- timeout/cancellation behavior;
- response parsing;
- provider metadata.

The core should know only normalized JEVe semantics:

```text
JudgmentPlan
JudgmentQuestion
JudgmentResult
JudgmentBundle
```

If a provider cannot express a field such as calibrated probability semantics, leave that capability absent or mark it unknown. Do not manufacture calibration metadata.

Provider-native parallelism may be implemented as one multi-output request or several concurrent requests. The core contract is about independent semantic questions and correlated results, not a particular wire shape.

## 11. Synthetic-first testing

Before live integration, prove core behavior with synthetic fixtures.

A clean-room implementation should demonstrate:

- mechanical-only decisions without EVE running;
- deterministic generation of judgment questions;
- parallel scheduling of independent fake judgments;
- judgment type/range/calibration validation;
- deterministic policy composition;
- stale bundle rejection;
- observation-epoch invalidation;
- selector mode as evidence rather than authority;
- outcome verification using simulated state transitions.

This keeps the architecture testable without importing external fixtures.

## 12. Independent naming

Use functional names derived from responsibilities:

```text
Observer
Normalizer
CandidateGenerator
DeterministicReducer
JudgmentPlanner
JudgmentScheduler
JEVAdapter
JudgmentBundleValidator
ActionPolicy
DecisionValidator
ActionCompiler
Executor
OutcomeVerifier
ReplayRunner
```

Do not preserve foreign component names merely because an existing implementation uses them.

When a generic computer-science term is the clearest name, use it normally.

## 13. Thresholds and constants

All non-trivial thresholds should be one of:

```text
specified by an external public contract
measured independently
configured by the operator
chosen as an explicit MVP policy default
```

A policy default should be labeled as such and should be easy to change.

Do not present an arbitrary copied value as a domain law.

## 14. Judgment schemas and domain semantics

Judgment types themselves may contain domain knowledge.

For each non-obvious judgment type, document independently:

```text
name
semantic question
required input feature classes
output kind
output semantics
comparability rules
calibration assumptions
freshness dependencies
known limitations
```

Do not copy another implementation's hidden judgment taxonomy merely because it appears effective.

## 15. AI-agent instructions for clean-room work

An AI implementing JEVe should follow this sequence:

1. read `README.md`, `docs/ARCHITECTURE.md`, `docs/JEV_JUDGMENT_MODEL.md`, and `docs/DETAILED_DESIGN.md`;
2. state the invariant being implemented;
3. define or reuse the JEVe-facing semantic contract;
4. identify which facts are public/documented, directly observed, inferred, or unknown;
5. implement against synthetic fixtures first;
6. keep provider/client-specific code behind adapters;
7. avoid importing names/structures from unrelated repositories;
8. add a regression fixture for every subtle boundary discovered;
9. preserve explicit uncertainty and fail-closed behavior;
10. document any new externally derived assumption.

## 16. Review checklist

A clean-room review should ask:

- Can this change be understood using only the JEVe repository and cited public/direct evidence?
- Does the core depend on an external implementation's private shape?
- Are foreign identifiers or constants present without independent reason?
- Are provider-specific parallel/batching details isolated behind the adapter?
- Are judgment semantics and calibration assumptions explicit?
- Are external assumptions isolated behind adapters or configuration?
- Are unknowns explicitly represented?
- Could the JEV provider or EVE integration be replaced without changing action policy semantics?
- Are synthetic tests sufficient to exercise the core behavior?

If the answer to the first or last two questions is no, the boundary is probably too coupled.
