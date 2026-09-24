from __future__ import annotations

from dataclasses import dataclass

from .model import (
    ActionKind,
    BundleReason,
    BundleValidation,
    BundleValidationStatus,
    CalibrationRequirement,
    CalibrationStatus,
    Criticality,
    Elimination,
    ExecutionEvidence,
    ExecutionPlan,
    FreshValidation,
    FreshValidationReason,
    HardConstraints,
    JudgmentBundle,
    JudgmentOutputContract,
    JudgmentPlan,
    JudgmentQuestion,
    JudgmentResult,
    KnowledgeStatus,
    OutcomeStage,
    OutcomeVerification,
    PhysicalStep,
    PolicyDecision,
    PolicyStatus,
    ReductionReason,
    ReductionResult,
    ResultStatus,
    SemanticAction,
    StateSnapshot,
    ValidatedDecision,
    ValidatedJudgmentBundle,
    ValueKind,
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
                    eliminated.append(
                        Elimination(candidate.candidate_id, ReductionReason.UNAVAILABLE_ACTION)
                    )
                    continue

                if route.reachable.status is KnowledgeStatus.KNOWN:
                    if route.reachable.value is not True:
                        eliminated.append(
                            Elimination(
                                candidate.candidate_id,
                                ReductionReason.INVALID_PRECONDITION,
                            )
                        )
                        continue
                else:
                    eliminated.append(
                        Elimination(
                            candidate.candidate_id,
                            ReductionReason.PRECONDITION_UNRESOLVED,
                        )
                    )
                    continue

                if self._violates_route_constraints(route.route_id, route.length, snapshot.constraints):
                    eliminated.append(
                        Elimination(
                            candidate.candidate_id,
                            ReductionReason.HARD_CONSTRAINT_VIOLATION,
                        )
                    )
                    continue

                surviving.append(candidate)
                continue

            if candidate.kind is ActionKind.RETREAT:
                if snapshot.retreat_available.status is KnowledgeStatus.KNOWN:
                    if snapshot.retreat_available.value is not True:
                        eliminated.append(
                            Elimination(candidate.candidate_id, ReductionReason.UNAVAILABLE_ACTION)
                        )
                        continue
                else:
                    eliminated.append(
                        Elimination(
                            candidate.candidate_id,
                            ReductionReason.PRECONDITION_UNRESOLVED,
                        )
                    )
                    continue

                surviving.append(candidate)
                continue

            eliminated.append(
                Elimination(candidate.candidate_id, ReductionReason.UNAVAILABLE_ACTION)
            )

        surviving, dominance_eliminations = self._remove_exactly_dominated_routes(
            snapshot, surviving
        )
        eliminated.extend(dominance_eliminations)

        unresolved: list[str] = []
        for candidate in surviving:
            if candidate.kind is ActionKind.TAKE_ROUTE:
                route = route_by_id[candidate.route_id or ""]
                if route.exact_risk.status is not KnowledgeStatus.KNOWN:
                    unresolved.append(f"ROUTE_RISK:{route.route_id}")
            elif candidate.kind is ActionKind.RETREAT:
                if snapshot.exact_should_disengage.status is not KnowledgeStatus.KNOWN:
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
        if route_id in constraints.forbidden_route_ids:
            return True
        if constraints.max_route_length is not None and length > constraints.max_route_length:
            return True
        return False

    def _remove_exactly_dominated_routes(
        self,
        snapshot: StateSnapshot,
        surviving: list[SemanticAction],
    ) -> tuple[list[SemanticAction], list[Elimination]]:
        route_by_id = {route.route_id: route for route in snapshot.routes}
        route_candidates = [
            candidate
            for candidate in surviving
            if candidate.kind is ActionKind.TAKE_ROUTE
        ]

        dominated_ids: set[str] = set()
        for candidate in route_candidates:
            route = route_by_id[candidate.route_id or ""]
            if route.exact_risk.status is not KnowledgeStatus.KNOWN:
                continue
            assert route.exact_risk.value is not None
            for other_candidate in route_candidates:
                if other_candidate.candidate_id == candidate.candidate_id:
                    continue
                other = route_by_id[other_candidate.route_id or ""]
                if other.exact_risk.status is not KnowledgeStatus.KNOWN:
                    continue
                assert other.exact_risk.value is not None
                no_worse = (
                    other.exact_risk.value <= route.exact_risk.value
                    and other.length <= route.length
                )
                strictly_better = (
                    other.exact_risk.value < route.exact_risk.value
                    or other.length < route.length
                )
                if no_worse and strictly_better:
                    dominated_ids.add(candidate.candidate_id)
                    break

        if not dominated_ids:
            return surviving, []

        kept = [
            candidate
            for candidate in surviving
            if candidate.candidate_id not in dominated_ids
        ]
        eliminated = [
            Elimination(candidate_id, ReductionReason.STRICTLY_DOMINATED_EXACT_OPTION)
            for candidate_id in sorted(dominated_ids)
        ]
        return kept, eliminated


class JudgmentPlanner:
    def plan(
        self,
        snapshot: StateSnapshot,
        reduction: ReductionResult,
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
                            semantics=(
                                "Estimated contextual probability-like risk for this route "
                                "within the originating snapshot"
                            ),
                            numeric_range=(0.0, 1.0),
                            calibration_requirement=CalibrationRequirement.CALIBRATED,
                            abstention_allowed=False,
                        ),
                        criticality=Criticality.REQUIRED,
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
                            semantics=(
                                "Estimated probability-like support for disengagement "
                                "in the current semantic context"
                            ),
                            numeric_range=(0.0, 1.0),
                            calibration_requirement=CalibrationRequirement.CALIBRATED,
                            abstention_allowed=False,
                        ),
                        criticality=Criticality.REQUIRED,
                    )
                )
            else:
                raise ValueError(f"unsupported unresolved dimension: {dimension}")

        questions_tuple = tuple(questions)
        return JudgmentPlan(
            plan_id=self._plan_id(snapshot, questions_tuple),
            snapshot_id=snapshot.snapshot_id,
            observation_epoch=snapshot.observation_epoch,
            questions=questions_tuple,
            required_question_ids=tuple(
                q.question_id
                for q in questions_tuple
                if q.criticality is Criticality.REQUIRED
            ),
            optional_question_ids=tuple(
                q.question_id
                for q in questions_tuple
                if q.criticality is Criticality.OPTIONAL
            ),
        )

    @staticmethod
    def _plan_id(
        snapshot: StateSnapshot,
        questions: tuple[JudgmentQuestion, ...],
    ) -> str:
        question_part = ",".join(question.question_id for question in questions) or "none"
        return (
            f"plan:{snapshot.snapshot_id}:oe{snapshot.observation_epoch}:"
            f"{question_part}"
        )


@dataclass(frozen=True)
class ScriptedAnswer:
    status: ResultStatus
    value_kind: ValueKind | None = None
    value: float | None = None
    calibration: CalibrationStatus = CalibrationStatus.UNKNOWN
    completed_at: int = 0
    fresh_until: int = 0
    question_id_override: str | None = None
    snapshot_id_override: str | None = None
    observation_epoch_override: int | None = None


class FakeJEVAdapter:
    def __init__(self, scripts: dict[str, ScriptedAnswer]) -> None:
        self._scripts = dict(scripts)
        self.call_count = 0

    def evaluate(
        self,
        plan: JudgmentPlan,
        question: JudgmentQuestion,
    ) -> JudgmentResult:
        self.call_count += 1
        scripted = self._scripts.get(
            question.question_id,
            ScriptedAnswer(
                status=ResultStatus.ERROR,
                completed_at=0,
                fresh_until=0,
            ),
        )
        return JudgmentResult(
            question_id=scripted.question_id_override or question.question_id,
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
        )


@dataclass(frozen=True)
class ScheduledJudgments:
    waves: tuple[tuple[str, ...], ...]
    results: tuple[JudgmentResult, ...]


class JudgmentScheduler:
    def execute(
        self,
        plan: JudgmentPlan,
        adapter: FakeJEVAdapter,
    ) -> ScheduledJudgments:
        waves = self.build_waves(plan)
        question_by_id = {q.question_id: q for q in plan.questions}
        results: list[JudgmentResult] = []

        for wave in waves:
            for question_id in wave:
                results.append(adapter.evaluate(plan, question_by_id[question_id]))

        return ScheduledJudgments(waves=waves, results=tuple(results))

    def build_waves(self, plan: JudgmentPlan) -> tuple[tuple[str, ...], ...]:
        pending = {question.question_id: question for question in plan.questions}
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


@dataclass(frozen=True)
class BundleValidationPolicy:
    now: int
    allow_missing_optional: bool = False


class JudgmentBundleValidator:
    def validate(
        self,
        snapshot: StateSnapshot,
        plan: JudgmentPlan,
        results: tuple[JudgmentResult, ...],
        policy: BundleValidationPolicy,
    ) -> BundleValidation:
        reasons: list[BundleReason] = []
        question_by_id = {question.question_id: question for question in plan.questions}
        result_by_id: dict[str, JudgmentResult] = {}

        for result in results:
            if result.question_id in result_by_id:
                reasons.append(BundleReason.DUPLICATE_RESULT)
                continue
            result_by_id[result.question_id] = result

            question = question_by_id.get(result.question_id)
            if question is None:
                reasons.append(BundleReason.UNKNOWN_QUESTION)
                continue

            if result.snapshot_id != plan.snapshot_id:
                reasons.append(BundleReason.SNAPSHOT_MISMATCH)
            if result.observation_epoch != plan.observation_epoch:
                reasons.append(BundleReason.OBSERVATION_EPOCH_MISMATCH)

            if result.status is ResultStatus.ANSWERED:
                if policy.now > result.fresh_until:
                    reasons.append(BundleReason.RESULT_STALE)
                self._validate_answer(question, result, reasons)
            elif result.status is ResultStatus.ABSTAIN:
                if not question.output_contract.abstention_allowed:
                    reasons.append(BundleReason.ABSTENTION_NOT_ALLOWED)
            elif result.status is ResultStatus.ERROR:
                pass

        missing_required = tuple(
            question_id
            for question_id in plan.required_question_ids
            if question_id not in result_by_id
            or result_by_id[question_id].status is not ResultStatus.ANSWERED
        )
        missing_optional = tuple(
            question_id
            for question_id in plan.optional_question_ids
            if question_id not in result_by_id
            or result_by_id[question_id].status is not ResultStatus.ANSWERED
        )

        if missing_required:
            reasons.append(BundleReason.MISSING_REQUIRED)
        if missing_optional and not policy.allow_missing_optional:
            reasons.append(BundleReason.OPTIONAL_RESULT_MISSING)

        if snapshot.snapshot_id != plan.snapshot_id:
            reasons.append(BundleReason.SNAPSHOT_MISMATCH)
        if snapshot.observation_epoch != plan.observation_epoch:
            reasons.append(BundleReason.OBSERVATION_EPOCH_MISMATCH)
        if policy.now > snapshot.fresh_until:
            reasons.append(BundleReason.SNAPSHOT_STALE)

        bundle = JudgmentBundle(
            plan_id=plan.plan_id,
            snapshot_id=plan.snapshot_id,
            observation_epoch=plan.observation_epoch,
            results=results,
            missing_required=missing_required,
            missing_optional=missing_optional,
        )

        unique_reasons = tuple(dict.fromkeys(reasons))
        stale_reasons = {
            BundleReason.RESULT_STALE,
            BundleReason.SNAPSHOT_STALE,
            BundleReason.OBSERVATION_EPOCH_MISMATCH,
        }
        if any(reason in stale_reasons for reason in unique_reasons):
            return BundleValidation(
                BundleValidationStatus.STALE,
                unique_reasons,
                None,
            )
        if unique_reasons:
            return BundleValidation(
                BundleValidationStatus.INVALID,
                unique_reasons,
                None,
            )

        status = (
            BundleValidationStatus.PARTIAL
            if missing_optional
            else BundleValidationStatus.VALID
        )
        return BundleValidation(
            status=status,
            reasons=(),
            validated=ValidatedJudgmentBundle(bundle),
        )

    @staticmethod
    def _validate_answer(
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
        if not (low <= result.value <= high):
            reasons.append(BundleReason.NUMERIC_RANGE_INVALID)

        requirement = contract.calibration_requirement
        if requirement is CalibrationRequirement.CALIBRATED:
            if result.calibration is not CalibrationStatus.CALIBRATED:
                reasons.append(BundleReason.CALIBRATION_INSUFFICIENT)
        elif requirement is CalibrationRequirement.DECLARED:
            if result.calibration is CalibrationStatus.UNKNOWN:
                reasons.append(BundleReason.CALIBRATION_INSUFFICIENT)


@dataclass(frozen=True)
class PolicyConfig:
    disengage_threshold: float = 0.8


class DeterministicPolicy:
    def decide(
        self,
        snapshot: StateSnapshot,
        reduction: ReductionResult,
        bundle: ValidatedJudgmentBundle | None,
        config: PolicyConfig,
    ) -> PolicyDecision:
        surviving = {
            candidate.candidate_id: candidate
            for candidate in reduction.surviving_candidates
        }
        routes = {
            route.route_id: route
            for route in snapshot.routes
        }

        if reduction.unresolved_dimensions and bundle is None:
            return PolicyDecision(
                PolicyStatus.OBSERVE_MORE,
                None,
                ("SEMANTIC_EVIDENCE_REQUIRED",),
                snapshot.snapshot_id,
                snapshot.observation_epoch,
            )

        retreat_candidate = next(
            (
                candidate
                for candidate in reduction.surviving_candidates
                if candidate.kind is ActionKind.RETREAT
            ),
            None,
        )

        disengage = self._disengage_value(snapshot, bundle)
        if (
            retreat_candidate is not None
            and disengage is not None
            and disengage >= config.disengage_threshold
        ):
            return PolicyDecision(
                PolicyStatus.SELECTED,
                retreat_candidate,
                ("DISENGAGE_THRESHOLD_MET",),
                snapshot.snapshot_id,
                snapshot.observation_epoch,
            )

        scored_routes: list[tuple[float, int, str, SemanticAction]] = []
        for candidate in reduction.surviving_candidates:
            if candidate.kind is not ActionKind.TAKE_ROUTE:
                continue
            route = routes[candidate.route_id or ""]
            risk = self._route_risk(route.route_id, route.exact_risk, bundle)
            if risk is None:
                return PolicyDecision(
                    PolicyStatus.OBSERVE_MORE,
                    None,
                    ("ROUTE_RISK_MISSING",),
                    snapshot.snapshot_id,
                    snapshot.observation_epoch,
                )
            if risk <= snapshot.objective.risk_tolerance:
                scored_routes.append((risk, route.length, route.route_id, candidate))

        if scored_routes:
            _, _, _, selected = min(scored_routes)
            return PolicyDecision(
                PolicyStatus.SELECTED,
                selected,
                ("LOWEST_ACCEPTABLE_ROUTE_RISK",),
                snapshot.snapshot_id,
                snapshot.observation_epoch,
            )

        if "WAIT" in surviving:
            return PolicyDecision(
                PolicyStatus.WAIT,
                None,
                ("NO_ROUTE_WITHIN_RISK_TOLERANCE",),
                snapshot.snapshot_id,
                snapshot.observation_epoch,
            )

        return PolicyDecision(
            PolicyStatus.FAIL_CLOSED,
            None,
            ("NO_SAFE_POLICY_BRANCH",),
            snapshot.snapshot_id,
            snapshot.observation_epoch,
        )

    @staticmethod
    def _route_risk(route_id, exact_risk, bundle):
        if exact_risk.status is KnowledgeStatus.KNOWN:
            return exact_risk.value
        if bundle is None:
            return None
        return bundle.result(f"route-risk:{route_id}").value

    @staticmethod
    def _disengage_value(snapshot: StateSnapshot, bundle):
        if snapshot.exact_should_disengage.status is KnowledgeStatus.KNOWN:
            return snapshot.exact_should_disengage.value
        if bundle is None:
            return None
        try:
            return bundle.result("should-disengage").value
        except KeyError:
            return None


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
        now: int,
    ) -> FreshValidation:
        if decision.status is not PolicyStatus.SELECTED or decision.selected_action is None:
            return FreshValidation(
                False,
                (FreshValidationReason.NOT_SELECTED,),
                None,
            )

        if fresh_snapshot.observation_epoch != decision.observation_epoch:
            return FreshValidation(
                False,
                (FreshValidationReason.OBSERVATION_EPOCH_CHANGED,),
                None,
            )

        if now > fresh_snapshot.fresh_until:
            return FreshValidation(
                False,
                (FreshValidationReason.FRESH_SNAPSHOT_STALE,),
                None,
            )

        action = decision.selected_action
        if action.kind is ActionKind.TAKE_ROUTE:
            route = next(
                (r for r in fresh_snapshot.routes if r.route_id == action.route_id),
                None,
            )
            if route is None:
                return FreshValidation(
                    False,
                    (FreshValidationReason.SELECTED_CANDIDATE_DISAPPEARED,),
                    None,
                )
            if not route.available:
                return FreshValidation(
                    False,
                    (FreshValidationReason.ACTION_UNAVAILABLE,),
                    None,
                )
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
            if (
                fresh_snapshot.retreat_destination_id != action.destination_id
            ):
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

        validated = ValidatedDecision(
            action=action,
            validation_snapshot_id=fresh_snapshot.snapshot_id,
            validation_observation_epoch=fresh_snapshot.observation_epoch,
        )
        return FreshValidation(True, (), validated)


class SimulatedActionCompiler:
    def compile(self, decision: ValidatedDecision) -> ExecutionPlan:
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
        # `plan` is intentionally consumed but never reinterpreted into a new action.
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
