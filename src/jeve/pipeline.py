from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic, sleep
from math import isfinite
from typing import Callable

from .model import (
    ActionKind,
    BundleReason,
    BundleValidation,
    BundleValidationStatus,
    CalibrationProvenance,
    CalibrationRequirement,
    CalibrationStatus,
    Criticality,
    DecisionTrace,
    Elimination,
    ExecutionEvidence,
    ExecutionPlan,
    FreshValidation,
    FreshValidationReason,
    HardConstraints,
    IntentAdmission,
    IntentAdmissionStatus,
    JudgmentBinding,
    JudgmentBundle,
    JudgmentOutputContract,
    JudgmentPlan,
    JudgmentQuestion,
    JudgmentResult,
    KnowledgeStatus,
    OutcomeStage,
    OutcomeVerification,
    PendingIntent,
    PhysicalStep,
    PolicyDecision,
    PolicyStatus,
    PolicyUsableJudgmentBundle,
    ReductionReason,
    ReductionResult,
    ResultStatus,
    SemanticAction,
    StateSnapshot,
    ValidatedDecision,
    ValueKind,
)


def _hash_canonical(value) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _knowledge_payload(value):
    return {
        "status": value.status.value,
        "value": value.value if value.status is KnowledgeStatus.KNOWN else None,
    }


def semantic_snapshot_key(snapshot: StateSnapshot) -> str:
    routes = [
        {
            "route_id": route.route_id,
            "reachable": _knowledge_payload(route.reachable),
            "length": route.length,
            "available": route.available,
            "exact_risk": _knowledge_payload(route.exact_risk),
        }
        for route in sorted(snapshot.routes, key=lambda item: item.route_id)
    ]
    material = {
        "objective": {
            "destination_id": snapshot.objective.destination_id,
            "risk_tolerance": snapshot.objective.risk_tolerance,
        },
        "constraints": {
            "max_route_length": snapshot.constraints.max_route_length,
            "forbidden_route_ids": sorted(snapshot.constraints.forbidden_route_ids),
        },
        "routes": routes,
        "retreat_destination_id": snapshot.retreat_destination_id,
        "retreat_available": _knowledge_payload(snapshot.retreat_available),
        "exact_should_disengage": _knowledge_payload(snapshot.exact_should_disengage),
    }
    return _hash_canonical(material)


def judgment_equivalence_key(question: JudgmentQuestion) -> str:
    contract = question.output_contract
    material = {
        "judgment_type": question.judgment_type,
        "subject_id": question.subject_id,
        "feature_names": sorted(name for name, _ in question.feature_slice),
        "value_kind": contract.value_kind.value,
        "semantics": contract.semantics,
        "numeric_range": list(contract.numeric_range),
        "calibration_requirement": contract.calibration_requirement.value,
        "abstention_allowed": contract.abstention_allowed,
        "schema_version": question.schema_version,
        "correlation_key": question.correlation_key,
        "depends_on": sorted(question.depends_on),
    }
    return _hash_canonical(material)


def judgment_dependency_key(question: JudgmentQuestion) -> str:
    return _hash_canonical(
        {
            "feature_slice": sorted(question.feature_slice),
            "freshness_dependencies": sorted(question.freshness_dependencies),
        }
    )


@dataclass(frozen=True)
class JudgmentFreshnessPolicy:
    max_age: int

    def __post_init__(self) -> None:
        if self.max_age < 0:
            raise ValueError("max_age must be non-negative")


@dataclass(frozen=True)
class CalibrationPolicy:
    accepted_authorities: tuple[str, ...]
    evaluation_population: str
    metric_name: str
    max_metric_value: float

    def __post_init__(self) -> None:
        if not self.accepted_authorities:
            raise ValueError("at least one calibration authority is required")
        if not self.evaluation_population.strip() or not self.metric_name.strip():
            raise ValueError("calibration population and metric are required")
        if not 0.0 <= self.max_metric_value <= 1.0:
            raise ValueError("max_metric_value must be within [0, 1]")

    @property
    def key(self) -> str:
        return _hash_canonical(
            {
                "accepted_authorities": sorted(self.accepted_authorities),
                "evaluation_population": self.evaluation_population,
                "metric_name": self.metric_name,
                "max_metric_value": self.max_metric_value,
            }
        )


@dataclass(frozen=True)
class PolicyConfig:
    disengage_threshold: float = 0.8
    decision_ttl: int = 30

    def __post_init__(self) -> None:
        if not 0.0 <= self.disengage_threshold <= 1.0:
            raise ValueError("disengage_threshold must be within [0, 1]")
        if self.decision_ttl < 0:
            raise ValueError("decision_ttl must be non-negative")

    @property
    def key(self) -> str:
        return _hash_canonical(
            {
                "disengage_threshold": self.disengage_threshold,
                "decision_ttl": self.decision_ttl,
            }
        )


class CandidateGenerator:
    def generate(self, snapshot: StateSnapshot) -> tuple[SemanticAction, ...]:
        candidates: list[SemanticAction] = [SemanticAction.wait()]
        candidates.extend(SemanticAction.take_route(route.route_id) for route in snapshot.routes)
        if snapshot.retreat_destination_id is not None:
            candidates.append(SemanticAction.retreat(snapshot.retreat_destination_id))
        return tuple(candidates)


class DeterministicReducer:
    def reduce(
        self,
        snapshot: StateSnapshot,
        candidates: tuple[SemanticAction, ...],
    ) -> ReductionResult:
        route_by_id = {route.route_id: route for route in snapshot.routes}
        surviving: list[SemanticAction] = []
        eliminated: list[Elimination] = []

        for candidate in candidates:
            if candidate.kind is ActionKind.WAIT:
                surviving.append(candidate)
                continue

            if candidate.kind is ActionKind.TAKE_ROUTE:
                route = route_by_id.get(candidate.route_id or "")
                if route is None or not route.available:
                    eliminated.append(Elimination(candidate.candidate_id, ReductionReason.UNAVAILABLE_ACTION))
                    continue
                if route.reachable.status is not KnowledgeStatus.KNOWN:
                    eliminated.append(Elimination(candidate.candidate_id, ReductionReason.PRECONDITION_UNRESOLVED))
                    continue
                if route.reachable.value is not True:
                    eliminated.append(Elimination(candidate.candidate_id, ReductionReason.INVALID_PRECONDITION))
                    continue
                if self._violates_route_constraints(route.route_id, route.length, snapshot.constraints):
                    eliminated.append(
                        Elimination(candidate.candidate_id, ReductionReason.HARD_CONSTRAINT_VIOLATION)
                    )
                    continue
                surviving.append(candidate)
                continue

            if candidate.kind is ActionKind.RETREAT:
                if snapshot.retreat_available.status is not KnowledgeStatus.KNOWN:
                    eliminated.append(Elimination(candidate.candidate_id, ReductionReason.PRECONDITION_UNRESOLVED))
                    continue
                if snapshot.retreat_available.value is not True:
                    eliminated.append(Elimination(candidate.candidate_id, ReductionReason.UNAVAILABLE_ACTION))
                    continue
                surviving.append(candidate)
                continue

            eliminated.append(Elimination(candidate.candidate_id, ReductionReason.UNAVAILABLE_ACTION))

        surviving, dominance = self._remove_exactly_dominated_routes(snapshot, surviving)
        eliminated.extend(dominance)

        unresolved: list[str] = []
        for candidate in surviving:
            if candidate.kind is ActionKind.TAKE_ROUTE:
                route = route_by_id[candidate.route_id or ""]
                if route.exact_risk.status is not KnowledgeStatus.KNOWN:
                    unresolved.append(f"ROUTE_RISK:{route.route_id}")
            elif (
                candidate.kind is ActionKind.RETREAT
                and snapshot.exact_should_disengage.status is not KnowledgeStatus.KNOWN
            ):
                unresolved.append("SHOULD_DISENGAGE:CURRENT_CONTEXT")

        return ReductionResult(
            surviving_candidates=tuple(surviving),
            eliminated=tuple(eliminated),
            unresolved_dimensions=tuple(unresolved),
        )

    @staticmethod
    def _violates_route_constraints(
        route_id: str,
        length: int,
        constraints: HardConstraints,
    ) -> bool:
        return (
            route_id in constraints.forbidden_route_ids
            or (
                constraints.max_route_length is not None
                and length > constraints.max_route_length
            )
        )

    def _remove_exactly_dominated_routes(
        self,
        snapshot: StateSnapshot,
        surviving: list[SemanticAction],
    ) -> tuple[list[SemanticAction], list[Elimination]]:
        route_by_id = {route.route_id: route for route in snapshot.routes}
        route_candidates = [
            candidate for candidate in surviving if candidate.kind is ActionKind.TAKE_ROUTE
        ]
        dominated: set[str] = set()

        for candidate in route_candidates:
            route = route_by_id[candidate.route_id or ""]
            if route.exact_risk.status is not KnowledgeStatus.KNOWN:
                continue
            for other_candidate in route_candidates:
                if other_candidate.candidate_id == candidate.candidate_id:
                    continue
                other = route_by_id[other_candidate.route_id or ""]
                if other.exact_risk.status is not KnowledgeStatus.KNOWN:
                    continue
                no_worse = (
                    other.exact_risk.value <= route.exact_risk.value
                    and other.length <= route.length
                )
                strictly_better = (
                    other.exact_risk.value < route.exact_risk.value
                    or other.length < route.length
                )
                if no_worse and strictly_better:
                    dominated.add(candidate.candidate_id)
                    break

        return (
            [candidate for candidate in surviving if candidate.candidate_id not in dominated],
            [
                Elimination(candidate_id, ReductionReason.STRICTLY_DOMINATED_EXACT_OPTION)
                for candidate_id in sorted(dominated)
            ],
        )


class JudgmentPlanner:
    def plan(
        self,
        snapshot: StateSnapshot,
        reduction: ReductionResult,
        *,
        include_optional_context: bool = False,
    ) -> JudgmentPlan:
        questions: list[JudgmentQuestion] = []

        for dimension in reduction.unresolved_dimensions:
            if dimension.startswith("ROUTE_RISK:"):
                route_id = dimension.split(":", 1)[1]
                route = next(route for route in snapshot.routes if route.route_id == route_id)
                questions.append(
                    JudgmentQuestion(
                        question_id=f"route-risk:{route_id}",
                        judgment_type="ROUTE_RISK",
                        subject_id=route_id,
                        feature_slice=(
                            ("route_length", str(route.length)),
                            ("risk_tolerance", str(snapshot.objective.risk_tolerance)),
                        ),
                        output_contract=JudgmentOutputContract(
                            value_kind=ValueKind.PROBABILITY,
                            semantics="Estimated contextual route-risk probability",
                            numeric_range=(0.0, 1.0),
                            calibration_requirement=CalibrationRequirement.CALIBRATED,
                            abstention_allowed=False,
                        ),
                        criticality=Criticality.REQUIRED,
                        freshness_dependencies=(
                            f"route:{route_id}:length",
                            "objective:risk_tolerance",
                            "local:risk-context",
                        ),
                        correlation_key="current-route-risk-context",
                        schema_version="route-risk-v1",
                    )
                )
            elif dimension == "SHOULD_DISENGAGE:CURRENT_CONTEXT":
                questions.append(
                    JudgmentQuestion(
                        question_id="should-disengage",
                        judgment_type="SHOULD_DISENGAGE",
                        subject_id="current-context",
                        feature_slice=(
                            ("retreat_available", "true"),
                            ("risk_tolerance", str(snapshot.objective.risk_tolerance)),
                        ),
                        output_contract=JudgmentOutputContract(
                            value_kind=ValueKind.PROBABILITY,
                            semantics="Estimated probability that current context supports disengagement",
                            numeric_range=(0.0, 1.0),
                            calibration_requirement=CalibrationRequirement.CALIBRATED,
                            abstention_allowed=False,
                        ),
                        criticality=Criticality.REQUIRED,
                        freshness_dependencies=(
                            "retreat:availability",
                            "objective:risk_tolerance",
                            "local:risk-context",
                        ),
                        correlation_key="current-route-risk-context",
                        schema_version="disengage-v1",
                    )
                )
            else:
                raise ValueError(f"unsupported unresolved dimension: {dimension}")

        if include_optional_context:
            questions.append(
                JudgmentQuestion(
                    question_id="optional-context-note",
                    judgment_type="OPTIONAL_CONTEXT",
                    subject_id="current-context",
                    feature_slice=(("destination", snapshot.objective.destination_id),),
                    output_contract=JudgmentOutputContract(
                        value_kind=ValueKind.SCORE,
                        semantics="Optional diagnostic context score not required for action authority",
                        numeric_range=(0.0, 1.0),
                        calibration_requirement=CalibrationRequirement.NONE,
                        abstention_allowed=True,
                    ),
                    criticality=Criticality.OPTIONAL,
                    freshness_dependencies=("objective:destination",),
                    correlation_key=None,
                    schema_version="optional-context-v1",
                )
            )

        questions_tuple = tuple(questions)
        return JudgmentPlan(
            plan_id=f"plan:{snapshot.snapshot_id}:oe{snapshot.observation_epoch}:"
            + (",".join(q.question_id for q in questions_tuple) or "none"),
            snapshot_id=snapshot.snapshot_id,
            observation_epoch=snapshot.observation_epoch,
            questions=questions_tuple,
            required_question_ids=tuple(
                q.question_id for q in questions_tuple if q.criticality is Criticality.REQUIRED
            ),
            optional_question_ids=tuple(
                q.question_id for q in questions_tuple if q.criticality is Criticality.OPTIONAL
            ),
            semantic_input_key=semantic_snapshot_key(snapshot),
        )


@dataclass(frozen=True)
class ScriptedAnswer:
    status: ResultStatus
    value_kind: ValueKind | None = None
    value: float | None = None
    calibration: CalibrationStatus = CalibrationStatus.UNKNOWN
    completed_at: int = 0
    fresh_until: int = 0
    provider_id: str = "fake-provider"
    model_id: str = "fake-model"
    schema_version: str | None = None
    calibration_provenance: CalibrationProvenance | None = None
    question_id_override: str | None = None
    snapshot_id_override: str | None = None
    observation_epoch_override: int | None = None
    block_until_cancel: bool = False


class FakeJEVAdapter:
    def __init__(self, scripts: dict[str, ScriptedAnswer]) -> None:
        self._scripts = dict(scripts)
        self.call_count = 0
        self._lock = threading.Lock()

    def evaluate(
        self,
        plan: JudgmentPlan,
        question: JudgmentQuestion,
        cancel_event: threading.Event | None = None,
    ) -> JudgmentResult:
        with self._lock:
            self.call_count += 1
        scripted = self._scripts.get(question.question_id, ScriptedAnswer(ResultStatus.ERROR))

        if scripted.block_until_cancel:
            if cancel_event is None:
                sleep(0.05)
            else:
                cancel_event.wait(timeout=1)
                if cancel_event.is_set():
                    return self._result(
                        plan,
                        question,
                        ScriptedAnswer(
                            ResultStatus.CANCELLED,
                            completed_at=scripted.completed_at,
                            provider_id=scripted.provider_id,
                            model_id=scripted.model_id,
                            schema_version=scripted.schema_version,
                        ),
                    )
        return self._result(plan, question, scripted)

    @staticmethod
    def _result(
        plan: JudgmentPlan,
        question: JudgmentQuestion,
        scripted: ScriptedAnswer,
    ) -> JudgmentResult:
        qid = scripted.question_id_override or question.question_id
        schema_version = scripted.schema_version or question.schema_version
        equivalence_key = judgment_equivalence_key(question)
        dependency_key = judgment_dependency_key(question)
        result_id = _hash_canonical(
            {
                "question_id": qid,
                "status": scripted.status.value,
                "value_kind": None if scripted.value_kind is None else scripted.value_kind.value,
                "value": scripted.value,
                "completed_at": scripted.completed_at,
                "provider_id": scripted.provider_id,
                "model_id": scripted.model_id,
                "schema_version": schema_version,
                "equivalence_key": equivalence_key,
                "dependency_key": dependency_key,
            }
        )
        return JudgmentResult(
            question_id=qid,
            status=scripted.status,
            value_kind=scripted.value_kind,
            value=scripted.value,
            calibration=scripted.calibration,
            snapshot_id=scripted.snapshot_id_override or plan.snapshot_id,
            observation_epoch=(
                scripted.observation_epoch_override
                if scripted.observation_epoch_override is not None
                else plan.observation_epoch
            ),
            completed_at=scripted.completed_at,
            fresh_until=scripted.fresh_until,
            result_id=result_id,
            provider_id=scripted.provider_id,
            model_id=scripted.model_id,
            schema_version=schema_version,
            equivalence_key=equivalence_key,
            dependency_key=dependency_key,
            calibration_provenance=scripted.calibration_provenance,
        )


@dataclass(frozen=True)
class ScheduledJudgments:
    waves: tuple[tuple[str, ...], ...]
    results: tuple[JudgmentResult, ...]
    cancelled_optional: tuple[str, ...] = ()
    failures: tuple[tuple[str, str], ...] = ()


class JudgmentScheduler:
    def __init__(self, *, max_workers: int = 8, timeout_seconds: float = 5.0) -> None:
        if type(max_workers) is not int or max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self.max_workers = max_workers
        self.timeout_seconds = timeout_seconds

    def build_waves(self, plan: JudgmentPlan) -> tuple[tuple[str, ...], ...]:
        pending = {question.question_id: question for question in plan.questions}
        if len(pending) != len(plan.questions):
            raise ValueError("duplicate judgment question identity")
        completed: set[str] = set()
        waves: list[tuple[str, ...]] = []
        while pending:
            ready = tuple(
                sorted(
                    question_id
                    for question_id, question in pending.items()
                    if set(question.depends_on).issubset(completed)
                )
            )
            if not ready:
                raise ValueError("judgment dependency cycle or missing dependency")
            waves.append(ready)
            for question_id in ready:
                completed.add(question_id)
                del pending[question_id]
        return tuple(waves)

    def execute(
        self,
        plan: JudgmentPlan,
        adapter: FakeJEVAdapter,
    ) -> ScheduledJudgments:
        return self._execute(plan, adapter, sufficient=None)

    def execute_until_policy_sufficient(
        self,
        plan: JudgmentPlan,
        adapter: FakeJEVAdapter,
        sufficient: Callable[[tuple[JudgmentResult, ...]], bool],
    ) -> ScheduledJudgments:
        if any(question.depends_on for question in plan.questions):
            raise ValueError("short-circuit currently supports one independent wave")
        return self._execute(plan, adapter, sufficient=sufficient)

    def _execute(self, plan, adapter, *, sufficient) -> ScheduledJudgments:
        waves = self.build_waves(plan)
        if not waves:
            return ScheduledJudgments((), ())
        questions = {q.question_id: q for q in plan.questions}
        results: dict[str, JudgmentResult] = {}
        failures: dict[str, str] = {}
        cancelled: list[str] = []
        deadline = monotonic() + self.timeout_seconds
        cancellation = threading.Event()
        executor = ThreadPoolExecutor(max_workers=self.max_workers)

        def collect(futures, ids):
            if not ids:
                return
            done, _ = wait(
                [futures[qid] for qid in ids],
                timeout=max(0.0, deadline - monotonic()),
            )
            for qid in ids:
                future = futures[qid]
                if future not in done:
                    failures[qid] = "DEADLINE_EXCEEDED"
                    future.cancel()
                else:
                    try:
                        results[qid] = future.result()
                    except Exception:
                        failures[qid] = "ADAPTER_EXCEPTION"

        try:
            for wave in waves:
                ready = []
                for qid in wave:
                    if monotonic() >= deadline:
                        failures[qid] = "DEADLINE_EXCEEDED"
                    elif any(
                        dep not in results or results[dep].status is not ResultStatus.ANSWERED
                        for dep in questions[qid].depends_on
                    ):
                        failures[qid] = "DEPENDENCY_UNAVAILABLE"
                    else:
                        ready.append(qid)
                # Required work gets priority when workers are saturated.
                ready.sort(key=lambda qid: (questions[qid].criticality is Criticality.OPTIONAL, qid))
                futures = {
                    qid: executor.submit(adapter.evaluate, plan, questions[qid], cancellation)
                    for qid in ready
                }
                if sufficient is None:
                    collect(futures, ready)
                    continue
                required = [qid for qid in ready if questions[qid].criticality is Criticality.REQUIRED]
                optional = [qid for qid in ready if questions[qid].criticality is Criticality.OPTIONAL]
                collect(futures, required)
                required_complete = all(
                    qid in results and results[qid].status is ResultStatus.ANSWERED
                    for qid in plan.required_question_ids
                )
                if required_complete and sufficient(tuple(results[qid] for qid in plan.required_question_ids)):
                    completed = [qid for qid in optional if futures[qid].done()]
                    collect(futures, completed)
                    for qid in optional:
                        if qid not in completed:
                            cancelled.append(qid)
                            futures[qid].cancel()
                    cancellation.set()
                else:
                    collect(futures, optional)
            return ScheduledJudgments(
                waves=waves,
                results=tuple(results[q.question_id] for q in plan.questions if q.question_id in results),
                cancelled_optional=tuple(cancelled),
                failures=tuple((q.question_id, failures[q.question_id]) for q in plan.questions if q.question_id in failures),
            )
        finally:
            cancellation.set()
            # A Python thread cannot forcibly stop a provider. Late results are
            # discarded; adapters must honor cancellation and transport timeouts.
            executor.shutdown(wait=False, cancel_futures=True)


class JudgmentBundleValidator:
    def __init__(
        self,
        freshness: JudgmentFreshnessPolicy,
        calibration_policy: CalibrationPolicy,
    ) -> None:
        self._freshness = freshness
        self._calibration_policy = calibration_policy

    def validate(
        self,
        snapshot: StateSnapshot,
        plan: JudgmentPlan,
        results: tuple[JudgmentResult, ...],
        *,
        now: int,
        allow_missing_optional: bool = True,
    ) -> BundleValidation:
        reasons: list[BundleReason] = []
        optional_reasons: list[tuple[str, BundleReason]] = []
        question_by_id = {question.question_id: question for question in plan.questions}
        result_by_id: dict[str, JudgmentResult] = {}
        seen: set[str] = set()
        valid_until_candidates = [snapshot.fresh_until]
        required = tuple(q.question_id for q in plan.questions if q.criticality is Criticality.REQUIRED)
        optional = tuple(q.question_id for q in plan.questions if q.criticality is Criticality.OPTIONAL)
        if (
            len(question_by_id) != len(plan.questions)
            or required != plan.required_question_ids
            or optional != plan.optional_question_ids
            or plan.semantic_input_key != semantic_snapshot_key(snapshot)
        ):
            reasons.append(BundleReason.PLAN_MISMATCH)

        for result in results:
            if result.question_id in seen:
                reasons.append(BundleReason.DUPLICATE_RESULT)
                continue
            seen.add(result.question_id)
            question = question_by_id.get(result.question_id)
            if question is None:
                reasons.append(BundleReason.UNKNOWN_QUESTION)
                continue
            local: list[BundleReason] = []
            if result.snapshot_id != plan.snapshot_id:
                local.append(BundleReason.SNAPSHOT_MISMATCH)
            if result.observation_epoch != plan.observation_epoch:
                local.append(BundleReason.OBSERVATION_EPOCH_MISMATCH)
            if result.equivalence_key != judgment_equivalence_key(question):
                local.append(BundleReason.EQUIVALENCE_KEY_MISMATCH)
            if result.dependency_key != judgment_dependency_key(question):
                local.append(BundleReason.DEPENDENCY_KEY_MISMATCH)
            if result.schema_version != question.schema_version:
                local.append(BundleReason.SCHEMA_MISMATCH)

            if result.status is ResultStatus.ERROR:
                local.append(BundleReason.PROVIDER_FAILURE)
            elif result.status is ResultStatus.ABSTAIN and not question.output_contract.abstention_allowed:
                local.append(BundleReason.ABSTENTION_NOT_ALLOWED)
            elif result.status is ResultStatus.ANSWERED:
                valid_until = result.completed_at + self._freshness.max_age
                if now > valid_until:
                    local.append(BundleReason.RESULT_STALE)
                if not snapshot.observed_at <= result.completed_at <= now:
                    local.append(BundleReason.INVALID_COMPLETION_TIME)
                self._validate_answer(question, result, local)

            if local:
                if question.criticality is Criticality.OPTIONAL and allow_missing_optional:
                    optional_reasons.extend((result.question_id, reason) for reason in local)
                else:
                    reasons.extend(local)
                continue
            if result.status is ResultStatus.ANSWERED:
                result_by_id[result.question_id] = result
                valid_until_candidates.append(result.completed_at + self._freshness.max_age)

        missing_required = tuple(qid for qid in required if qid not in result_by_id)
        missing_optional = tuple(qid for qid in optional if qid not in result_by_id)
        if missing_required:
            reasons.append(BundleReason.MISSING_REQUIRED)
        if missing_optional and not allow_missing_optional:
            reasons.append(BundleReason.OPTIONAL_RESULT_MISSING)
        if snapshot.snapshot_id != plan.snapshot_id:
            reasons.append(BundleReason.SNAPSHOT_MISMATCH)
        if snapshot.observation_epoch != plan.observation_epoch:
            reasons.append(BundleReason.OBSERVATION_EPOCH_MISMATCH)
        if not snapshot.observed_at <= now <= snapshot.fresh_until:
            reasons.append(BundleReason.SNAPSHOT_STALE)

        bundle = JudgmentBundle(
            plan_id=plan.plan_id,
            snapshot_id=plan.snapshot_id,
            observation_epoch=plan.observation_epoch,
            results=tuple(result_by_id[q.question_id] for q in plan.questions if q.question_id in result_by_id),
            missing_required=missing_required,
            missing_optional=missing_optional,
            semantic_input_key=plan.semantic_input_key,
        )
        unique = tuple(dict.fromkeys(reasons))
        diagnostics = tuple(optional_reasons)
        stale_reasons = {
            BundleReason.RESULT_STALE,
            BundleReason.SNAPSHOT_STALE,
            BundleReason.OBSERVATION_EPOCH_MISMATCH,
        }
        if any(reason in stale_reasons for reason in unique):
            return BundleValidation(BundleValidationStatus.STALE, unique, None, diagnostics)
        if unique:
            return BundleValidation(BundleValidationStatus.INVALID, unique, None, diagnostics)

        status = BundleValidationStatus.PARTIAL if missing_optional else BundleValidationStatus.VALID
        equivalence_keys = tuple(sorted((r.question_id, r.equivalence_key) for r in bundle.results))
        return BundleValidation(
            status,
            (),
            PolicyUsableJudgmentBundle._issue(bundle, equivalence_keys, min(valid_until_candidates)),
            diagnostics,
        )

    def _validate_answer(
        self,
        question: JudgmentQuestion,
        result: JudgmentResult,
        reasons: list[BundleReason],
    ) -> None:
        contract = question.output_contract
        if result.value_kind is not contract.value_kind:
            reasons.append(BundleReason.OUTPUT_KIND_MISMATCH)
            return
        if result.value is None:
            reasons.append(BundleReason.VALUE_MISSING)
            return
        low, high = contract.numeric_range
        if type(result.value) not in (int, float) or not low <= result.value <= high:
            reasons.append(BundleReason.NUMERIC_RANGE_INVALID)

        if contract.calibration_requirement is CalibrationRequirement.CALIBRATED:
            if result.calibration is not CalibrationStatus.CALIBRATED:
                reasons.append(BundleReason.CALIBRATION_INSUFFICIENT)
                return
            provenance = result.calibration_provenance
            if provenance is None:
                reasons.append(BundleReason.CALIBRATION_PROVENANCE_MISSING)
                return
            if (
                provenance.provider_id != result.provider_id
                or provenance.model_id != result.model_id
                or provenance.schema_version != result.schema_version
                or provenance.authority not in self._calibration_policy.accepted_authorities
                or provenance.evaluation_population != self._calibration_policy.evaluation_population
                or provenance.metric_name != self._calibration_policy.metric_name
                or provenance.metric_value > self._calibration_policy.max_metric_value
            ):
                reasons.append(BundleReason.CALIBRATION_PROVENANCE_MISMATCH)
        elif contract.calibration_requirement is CalibrationRequirement.DECLARED:
            if result.calibration is CalibrationStatus.UNKNOWN:
                reasons.append(BundleReason.CALIBRATION_INSUFFICIENT)


def _binding_from_result(result: JudgmentResult, valid_until: int) -> JudgmentBinding:
    assert result.value_kind is not None and result.value is not None
    return JudgmentBinding(
        question_id=result.question_id,
        result_id=result.result_id,
        value_kind=result.value_kind,
        value=result.value,
        equivalence_key=result.equivalence_key,
        provider_id=result.provider_id,
        model_id=result.model_id,
        schema_version=result.schema_version,
        dependency_key=result.dependency_key,
        valid_until=valid_until,
    )


class DeterministicPolicy:
    def decide(
        self,
        snapshot: StateSnapshot,
        reduction: ReductionResult,
        bundle: PolicyUsableJudgmentBundle | None,
        config: PolicyConfig,
        *,
        now: int | None = None,
    ) -> PolicyDecision:
        now = snapshot.observed_at if now is None else now
        bindings: list[JudgmentBinding] = []
        routes = {route.route_id: route for route in snapshot.routes}
        surviving = {candidate.candidate_id: candidate for candidate in reduction.surviving_candidates}

        def consume(question_id: str) -> float | None:
            if bundle is None:
                return None
            try:
                result = bundle.result(question_id)
            except KeyError:
                return None
            if result.status is not ResultStatus.ANSWERED or result.value is None:
                return None
            bindings.append(_binding_from_result(result, bundle.valid_until))
            return result.value

        def decision(
            status: PolicyStatus,
            selected: SemanticAction | None,
            reasons: tuple[str, ...],
        ) -> PolicyDecision:
            return PolicyDecision(
                status=status,
                selected_action=selected,
                reason_codes=reasons,
                evaluated_snapshot_id=snapshot.snapshot_id,
                observation_epoch=snapshot.observation_epoch,
                created_at=now,
                expires_at=min(snapshot.fresh_until, now + config.decision_ttl),
                semantic_input_key=semantic_snapshot_key(snapshot),
                policy_config_key=config.key,
                judgment_bindings=tuple(bindings),
            )

        if not snapshot.observed_at <= now <= snapshot.fresh_until:
            return decision(PolicyStatus.OBSERVE_MORE, None, ("SNAPSHOT_NOT_FRESH",))
        if bundle is not None and (
            bundle.bundle.snapshot_id != snapshot.snapshot_id
            or bundle.bundle.observation_epoch != snapshot.observation_epoch
            or bundle.bundle.semantic_input_key != semantic_snapshot_key(snapshot)
            or now > bundle.valid_until
            or any(r.completed_at > now for r in bundle.bundle.results)
        ):
            return decision(PolicyStatus.OBSERVE_MORE, None, ("BUNDLE_NOT_CURRENT",))

        if reduction.unresolved_dimensions and bundle is None:
            return decision(PolicyStatus.OBSERVE_MORE, None, ("SEMANTIC_EVIDENCE_REQUIRED",))

        retreat_candidate = next(
            (
                candidate
                for candidate in reduction.surviving_candidates
                if candidate.kind is ActionKind.RETREAT
            ),
            None,
        )
        disengage = None
        if retreat_candidate is not None:
            if snapshot.exact_should_disengage.status is KnowledgeStatus.KNOWN:
                disengage = snapshot.exact_should_disengage.value
            else:
                disengage = consume("should-disengage")
                if disengage is None:
                    return decision(PolicyStatus.OBSERVE_MORE, None, ("DISENGAGEMENT_EVIDENCE_MISSING",))
        if (
            retreat_candidate is not None
            and disengage is not None
            and disengage >= config.disengage_threshold
        ):
            return decision(
                PolicyStatus.SELECTED,
                retreat_candidate,
                ("DISENGAGE_THRESHOLD_MET",),
            )

        scored_routes: list[tuple[float, int, str, SemanticAction]] = []
        for candidate in reduction.surviving_candidates:
            if candidate.kind is not ActionKind.TAKE_ROUTE:
                continue
            route = routes[candidate.route_id or ""]
            if route.exact_risk.status is KnowledgeStatus.KNOWN:
                risk = route.exact_risk.value
            else:
                risk = consume(f"route-risk:{route.route_id}")
            if risk is None:
                return decision(PolicyStatus.OBSERVE_MORE, None, ("ROUTE_RISK_MISSING",))
            if risk <= snapshot.objective.risk_tolerance:
                scored_routes.append((risk, route.length, route.route_id, candidate))

        if scored_routes:
            _, _, _, selected = min(scored_routes)
            return decision(
                PolicyStatus.SELECTED,
                selected,
                ("LOWEST_ACCEPTABLE_ROUTE_RISK",),
            )
        if "WAIT" in surviving:
            return decision(
                PolicyStatus.WAIT,
                None,
                ("NO_ROUTE_WITHIN_RISK_TOLERANCE",),
            )
        return decision(PolicyStatus.FAIL_CLOSED, None, ("NO_SAFE_POLICY_BRANCH",))


class FreshStateValidator:
    def __init__(
        self,
        generator: CandidateGenerator | None = None,
        reducer: DeterministicReducer | None = None,
    ) -> None:
        self._generator = generator or CandidateGenerator()
        self._reducer = reducer or DeterministicReducer()

    def validate(
        self,
        decision: PolicyDecision,
        fresh_snapshot: StateSnapshot,
        *,
        bundle: PolicyUsableJudgmentBundle | None,
        config: PolicyConfig,
        now: int,
    ) -> FreshValidation:
        if decision.status is not PolicyStatus.SELECTED or decision.selected_action is None:
            return FreshValidation(False, (FreshValidationReason.NOT_SELECTED,), None)
        if not decision.created_at <= now <= decision.expires_at:
            return FreshValidation(False, (FreshValidationReason.DECISION_EXPIRED,), None)
        if fresh_snapshot.observation_epoch != decision.observation_epoch:
            return FreshValidation(
                False,
                (FreshValidationReason.OBSERVATION_EPOCH_CHANGED,),
                None,
            )
        if not fresh_snapshot.observed_at <= now <= fresh_snapshot.fresh_until:
            return FreshValidation(False, (FreshValidationReason.FRESH_SNAPSHOT_STALE,), None)
        if semantic_snapshot_key(fresh_snapshot) != decision.semantic_input_key:
            return FreshValidation(False, (FreshValidationReason.SEMANTIC_INPUTS_CHANGED,), None)
        if config.key != decision.policy_config_key:
            return FreshValidation(False, (FreshValidationReason.POLICY_CONFIG_CHANGED,), None)

        if decision.judgment_bindings:
            if bundle is None:
                return FreshValidation(False, (FreshValidationReason.JUDGMENT_EVIDENCE_CHANGED,), None)
            for binding in decision.judgment_bindings:
                if now > binding.valid_until or now > bundle.valid_until:
                    return FreshValidation(
                        False,
                        (FreshValidationReason.JUDGMENT_EVIDENCE_EXPIRED,),
                        None,
                    )
                try:
                    result = bundle.result(binding.question_id)
                except KeyError:
                    return FreshValidation(
                        False,
                        (FreshValidationReason.JUDGMENT_EVIDENCE_CHANGED,),
                        None,
                    )
                current = _binding_from_result(result, bundle.valid_until)
                if current != binding:
                    return FreshValidation(
                        False,
                        (FreshValidationReason.JUDGMENT_EVIDENCE_CHANGED,),
                        None,
                    )

        action = decision.selected_action
        if action.kind is ActionKind.TAKE_ROUTE:
            route = next((r for r in fresh_snapshot.routes if r.route_id == action.route_id), None)
            if route is None:
                return FreshValidation(
                    False,
                    (FreshValidationReason.SELECTED_CANDIDATE_DISAPPEARED,),
                    None,
                )
            if not route.available:
                return FreshValidation(False, (FreshValidationReason.ACTION_UNAVAILABLE,), None)
            if (
                route.reachable.status is not KnowledgeStatus.KNOWN
                or route.reachable.value is not True
            ):
                return FreshValidation(
                    False,
                    (FreshValidationReason.REQUIRED_PRECONDITION_NO_LONGER_HOLDS,),
                    None,
                )
            if DeterministicReducer._violates_route_constraints(
                route.route_id,
                route.length,
                fresh_snapshot.constraints,
            ):
                return FreshValidation(
                    False,
                    (FreshValidationReason.HARD_CONSTRAINT_CHANGED_INCOMPATIBLY,),
                    None,
                )

        if action.kind is ActionKind.RETREAT:
            if fresh_snapshot.retreat_destination_id != action.destination_id:
                return FreshValidation(
                    False,
                    (FreshValidationReason.SELECTED_CANDIDATE_DISAPPEARED,),
                    None,
                )
            if (
                fresh_snapshot.retreat_available.status is not KnowledgeStatus.KNOWN
                or fresh_snapshot.retreat_available.value is not True
            ):
                return FreshValidation(
                    False,
                    (FreshValidationReason.REQUIRED_PRECONDITION_NO_LONGER_HOLDS,),
                    None,
                )

        current = self._reducer.reduce(
            fresh_snapshot,
            self._generator.generate(fresh_snapshot),
        )
        if action.candidate_id not in {
            candidate.candidate_id for candidate in current.surviving_candidates
        }:
            return FreshValidation(
                False,
                (FreshValidationReason.SELECTED_CANDIDATE_DISAPPEARED,),
                None,
            )

        return FreshValidation(
            True,
            (),
            ValidatedDecision(
                action=action,
                validation_snapshot_id=fresh_snapshot.snapshot_id,
                validation_observation_epoch=fresh_snapshot.observation_epoch,
                resource_claims=action.resource_claims,
                validated_at=now,
                valid_until=min(decision.expires_at, fresh_snapshot.fresh_until, *(b.valid_until for b in decision.judgment_bindings)),
            ),
        )


class PendingIntentRegistry:
    def __init__(self) -> None:
        self._pending: dict[str, PendingIntent] = {}
        self._resource_owner: dict[str, str] = {}
        self._lock = threading.Lock()
        self._sequence = 0

    def admit(self, decision: ValidatedDecision, *, now: int) -> IntentAdmission:
        with self._lock:
            if not decision.validated_at <= now <= decision.valid_until:
                return IntentAdmission(IntentAdmissionStatus.DECISION_EXPIRED, None)
            action = decision.action
            if any(pending.action.candidate_id == action.candidate_id for pending in self._pending.values()):
                return IntentAdmission(IntentAdmissionStatus.DUPLICATE_PENDING_INTENT, None)
            if any(resource in self._resource_owner for resource in decision.resource_claims):
                return IntentAdmission(IntentAdmissionStatus.RESOURCE_BUSY, None)
            self._sequence += 1
            intent_id = _hash_canonical({
                "snapshot": decision.validation_snapshot_id,
                "epoch": decision.validation_observation_epoch,
                "candidate": action.candidate_id,
                "sequence": self._sequence,
            })
            pending = PendingIntent(intent_id, action, decision.resource_claims, decision)
            self._pending[intent_id] = pending
            for resource in pending.resource_claims:
                self._resource_owner[resource] = intent_id
            return IntentAdmission(IntentAdmissionStatus.ADMITTED, pending)

    def is_current(self, pending: PendingIntent, decision: ValidatedDecision, *, now: int) -> bool:
        with self._lock:
            return (
                decision.validated_at <= now <= decision.valid_until
                and pending.decision == decision
                and self._pending.get(pending.intent_id) == pending
                and all(self._resource_owner.get(resource) == pending.intent_id for resource in pending.resource_claims)
            )

    def resolve(self, intent_id: str) -> None:
        with self._lock:
            pending = self._pending.pop(intent_id, None)
            if pending is None:
                return
            for resource in pending.resource_claims:
                if self._resource_owner.get(resource) == intent_id:
                    del self._resource_owner[resource]


class SimulatedActionCompiler:
    def compile(
        self,
        decision: ValidatedDecision,
        admission: IntentAdmission,
        *,
        registry: PendingIntentRegistry,
        now: int,
    ) -> ExecutionPlan:
        if admission.status is not IntentAdmissionStatus.ADMITTED or admission.pending is None:
            raise ValueError("execution requires an admitted pending intent")
        if not registry.is_current(admission.pending, decision, now=now):
            raise ValueError("intent is not current for this validated decision")
        return ExecutionPlan(
            plan_id=f"exec:{decision.validation_snapshot_id}:{decision.action.candidate_id}",
            semantic_action=decision.action,
            compiled_from_snapshot=decision.validation_snapshot_id,
            observation_epoch=decision.validation_observation_epoch,
            steps=(
                PhysicalStep(
                    operation="SIMULATED_DELIVERY",
                    semantic_target=decision.action.candidate_id,
                ),
            ),
            resource_claims=decision.resource_claims,
        )


class SimulatedExecutor:
    def dispatch(
        self,
        plan: ExecutionPlan,
        *,
        command_accepted: bool,
        progressing: bool,
        final_effect: bool,
    ) -> ExecutionEvidence:
        _ = plan
        if final_effect:
            command_accepted = True
            progressing = True
        elif progressing:
            command_accepted = True
        return ExecutionEvidence(
            delivered=True,
            command_accepted=command_accepted,
            progressing=progressing,
            final_effect=final_effect,
        )


class OutcomeVerifier:
    def verify(self, evidence: ExecutionEvidence) -> OutcomeVerification:
        if evidence.final_effect:
            return OutcomeVerification(True, OutcomeStage.FINAL_EFFECT)
        if evidence.progressing:
            return OutcomeVerification(False, OutcomeStage.PROGRESSING)
        if evidence.command_accepted:
            return OutcomeVerification(False, OutcomeStage.COMMAND_ACCEPTED)
        if evidence.delivered:
            return OutcomeVerification(False, OutcomeStage.DELIVERED)
        return OutcomeVerification(False, OutcomeStage.NONE)


class ProbabilityFusion:
    @staticmethod
    def product(
        questions: tuple[JudgmentQuestion, ...],
        results: tuple[JudgmentResult, ...],
        *,
        independence_justification: str | None,
    ) -> float:
        if not independence_justification or not independence_justification.strip():
            raise ValueError("probability fusion requires explicit independence justification")
        correlation_keys = [
            question.correlation_key
            for question in questions
            if question.correlation_key is not None
        ]
        if len(correlation_keys) != len(set(correlation_keys)):
            raise ValueError("correlated judgments must not be multiplied as independent")
        by_id = {result.question_id: result for result in results}
        product = 1.0
        for question in questions:
            result = by_id[question.question_id]
            if result.value_kind is not ValueKind.PROBABILITY or result.value is None:
                raise ValueError("probability fusion requires probability results")
            product *= result.value
        return product


def reuse_allowed(
    question: JudgmentQuestion,
    result: JudgmentResult,
    *,
    now: int,
    freshness: JudgmentFreshnessPolicy,
    provider_id: str,
    model_id: str,
    observation_epoch: int,
    allow_cross_snapshot: bool = False,
) -> bool:
    if not allow_cross_snapshot:
        return False
    if result.status is not ResultStatus.ANSWERED:
        return False
    if not result.completed_at <= now <= result.completed_at + freshness.max_age:
        return False
    if result.observation_epoch != observation_epoch:
        return False
    if result.provider_id != provider_id or result.model_id != model_id:
        return False
    if result.schema_version != question.schema_version:
        return False
    if result.equivalence_key != judgment_equivalence_key(question):
        return False
    if result.dependency_key != judgment_dependency_key(question):
        return False
    return True


class TraceRecorder:
    @staticmethod
    def record(
        *,
        snapshot: StateSnapshot,
        reduction: ReductionResult,
        plan: JudgmentPlan,
        scheduled: ScheduledJudgments,
        validation: BundleValidation,
        freshness: JudgmentFreshnessPolicy,
        calibration_policy: CalibrationPolicy,
        policy_config: PolicyConfig,
        decision: PolicyDecision,
        fresh_validation: FreshValidation | None = None,
        execution_plan: ExecutionPlan | None = None,
        outcome: OutcomeVerification | None = None,
    ) -> DecisionTrace:
        return DecisionTrace(
            trace_id=_hash_canonical(
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "plan_id": plan.plan_id,
                    "decision_created_at": decision.created_at,
                    "selected": None
                    if decision.selected_action is None
                    else decision.selected_action.candidate_id,
                }
            ),
            snapshot=snapshot,
            reduction=reduction,
            judgment_plan=plan,
            judgment_results=scheduled.results,
            bundle_status=validation.status,
            judgment_freshness_max_age=freshness.max_age,
            calibration_policy_key=calibration_policy.key,
            policy_config_key=policy_config.key,
            policy_decision=decision,
            fresh_validation=fresh_validation,
            execution_plan=execution_plan,
            outcome=outcome,
            scheduler_failures=scheduled.failures,
            cancelled_optional=scheduled.cancelled_optional,
        )


class ReplayRunner:
    def replay(
        self,
        trace: DecisionTrace,
        *,
        calibration_policy: CalibrationPolicy,
        policy_config: PolicyConfig,
        now: int,
    ) -> PolicyDecision:
        if trace.calibration_policy_key != calibration_policy.key:
            raise ValueError("calibration policy differs from recorded trace")
        if trace.policy_config_key != policy_config.key:
            raise ValueError("policy config differs from recorded trace")

        freshness = JudgmentFreshnessPolicy(trace.judgment_freshness_max_age)
        validation = JudgmentBundleValidator(freshness, calibration_policy).validate(
            trace.snapshot,
            trace.judgment_plan,
            trace.judgment_results,
            now=now,
            allow_missing_optional=True,
        )
        if validation.status != trace.bundle_status:
            raise ValueError("bundle validation status diverged during replay")
        decision = DeterministicPolicy().decide(
            trace.snapshot,
            trace.reduction,
            validation.validated,
            policy_config,
            now=trace.policy_decision.created_at,
        )
        if decision != trace.policy_decision:
            raise ValueError("policy decision diverged during replay")
        return decision
