from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jeve.model import (
    BundleReason,
    BundleValidationStatus,
    CalibrationProvenance,
    CalibrationStatus,
    FreshValidationReason,
    HardConstraints,
    IntentAdmissionStatus,
    Knowledge,
    KnowledgeStatus,
    Objective,
    OutcomeStage,
    PolicyStatus,
    PolicyUsableJudgmentBundle,
    ResultStatus,
    RouteState,
    StateSnapshot,
    ValueKind,
)
from jeve.pipeline import (
    CalibrationPolicy,
    CandidateGenerator,
    DeterministicPolicy,
    DeterministicReducer,
    FakeJEVAdapter,
    FreshStateValidator,
    JudgmentBundleValidator,
    JudgmentFreshnessPolicy,
    JudgmentPlanner,
    JudgmentScheduler,
    OutcomeVerifier,
    PendingIntentRegistry,
    PolicyConfig,
    ProbabilityFusion,
    ReplayRunner,
    ScriptedAnswer,
    SimulatedActionCompiler,
    SimulatedExecutor,
    TraceRecorder,
    judgment_dependency_key,
    judgment_equivalence_key,
    reuse_allowed,
    semantic_snapshot_key,
)


def route(
    route_id: str,
    *,
    reachable: Knowledge[bool] | None = None,
    length: int,
    available: bool = True,
    exact_risk: Knowledge[float] | None = None,
) -> RouteState:
    return RouteState(
        route_id=route_id,
        reachable=reachable or Knowledge.known(True),
        length=length,
        available=available,
        exact_risk=exact_risk or Knowledge.unknown(),
    )


def snapshot(
    *,
    snapshot_id: str = "snapshot-1",
    observation_epoch: int = 7,
    state_epoch: int = 1,
    fresh_until: int = 200,
    routes: tuple[RouteState, ...] | None = None,
    constraints: HardConstraints | None = None,
    retreat_available: Knowledge[bool] | None = None,
    exact_should_disengage: Knowledge[float] | None = None,
    risk_tolerance: float = 0.50,
) -> StateSnapshot:
    return StateSnapshot(
        snapshot_id=snapshot_id,
        observation_epoch=observation_epoch,
        state_epoch=state_epoch,
        observed_at=10,
        fresh_until=fresh_until,
        objective=Objective(destination_id="destination", risk_tolerance=risk_tolerance),
        constraints=constraints or HardConstraints(),
        routes=routes or (route("A", length=10), route("B", length=15)),
        retreat_destination_id="safe-harbor",
        retreat_available=retreat_available or Knowledge.known(True),
        exact_should_disengage=exact_should_disengage or Knowledge.unknown(),
    )


CAL_POLICY = CalibrationPolicy(
    accepted_authorities=("synthetic-calibration-suite",),
    evaluation_population="navigation-risk-v1",
    metric_name="ECE",
    max_metric_value=0.10,
)
FRESHNESS = JudgmentFreshnessPolicy(max_age=100)
POLICY_CONFIG = PolicyConfig(disengage_threshold=0.8, decision_ttl=50)


def provenance(schema_version: str) -> CalibrationProvenance:
    return CalibrationProvenance(
        authority="synthetic-calibration-suite",
        basis="held-out replay calibration",
        provider_id="fake-provider",
        model_id="fake-model",
        schema_version=schema_version,
        evaluation_population="navigation-risk-v1",
        metric_name="ECE",
        metric_value=0.04,
    )


def ambiguous_scripts(*, optional_block: bool = False):
    return {
        "route-risk:A": ScriptedAnswer(
            ResultStatus.ANSWERED,
            ValueKind.PROBABILITY,
            0.72,
            CalibrationStatus.CALIBRATED,
            completed_at=20,
            calibration_provenance=provenance("route-risk-v1"),
        ),
        "route-risk:B": ScriptedAnswer(
            ResultStatus.ANSWERED,
            ValueKind.PROBABILITY,
            0.22,
            CalibrationStatus.CALIBRATED,
            completed_at=20,
            calibration_provenance=provenance("route-risk-v1"),
        ),
        "should-disengage": ScriptedAnswer(
            ResultStatus.ANSWERED,
            ValueKind.PROBABILITY,
            0.15,
            CalibrationStatus.CALIBRATED,
            completed_at=20,
            calibration_provenance=provenance("disengage-v1"),
        ),
        "optional-context-note": ScriptedAnswer(
            ResultStatus.ANSWERED,
            ValueKind.SCORE,
            0.5,
            CalibrationStatus.UNKNOWN,
            completed_at=20,
            block_until_cancel=optional_block,
        ),
    }


class ArchitectureCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = CandidateGenerator()
        self.reducer = DeterministicReducer()
        self.planner = JudgmentPlanner()
        self.scheduler = JudgmentScheduler()
        self.validator = JudgmentBundleValidator(FRESHNESS, CAL_POLICY)
        self.policy = DeterministicPolicy()

    def reduction_plan(self, state, *, optional=False):
        candidates = self.generator.generate(state)
        reduction = self.reducer.reduce(state, candidates)
        plan = self.planner.plan(state, reduction, include_optional_context=optional)
        return reduction, plan

    def validated(self, state, *, optional=False, scripts=None, now=30):
        reduction, plan = self.reduction_plan(state, optional=optional)
        scheduled = self.scheduler.execute(plan, FakeJEVAdapter(scripts or ambiguous_scripts()))
        validation = self.validator.validate(state, plan, scheduled.results, now=now)
        self.assertIsNotNone(validation.validated)
        return reduction, plan, scheduled, validation

    def test_knowledge_states_remain_distinct(self):
        self.assertNotEqual(Knowledge.unknown(), Knowledge.stale())
        self.assertNotEqual(Knowledge.stale(), Knowledge.transitional())
        self.assertEqual(Knowledge.known(False).status, KnowledgeStatus.KNOWN)

    def test_deterministic_only_zero_jev(self):
        state = snapshot(
            routes=(
                route("A", length=10, exact_risk=Knowledge.known(0.2)),
                route("B", length=15, exact_risk=Knowledge.known(0.2)),
            ),
            retreat_available=Knowledge.known(False),
            exact_should_disengage=Knowledge.known(0.0),
        )
        reduction, plan = self.reduction_plan(state)
        adapter = FakeJEVAdapter({})
        scheduled = self.scheduler.execute(plan, adapter)
        self.assertEqual(adapter.call_count, 0)
        self.assertEqual(scheduled.waves, ())
        decision = self.policy.decide(state, reduction, None, POLICY_CONFIG, now=30)
        self.assertEqual(decision.selected_action.candidate_id, "TAKE_ROUTE:A")
        self.assertEqual(decision.judgment_bindings, ())

    def test_parallel_bundle_and_policy_binding_include_consumed_evidence(self):
        state = snapshot()
        reduction, plan, scheduled, validation = self.validated(state)
        self.assertEqual(
            scheduled.waves,
            (("route-risk:A", "route-risk:B", "should-disengage"),),
        )
        decision = self.policy.decide(
            state, reduction, validation.validated, POLICY_CONFIG, now=30
        )
        self.assertEqual(decision.status, PolicyStatus.SELECTED)
        self.assertEqual(decision.selected_action.candidate_id, "TAKE_ROUTE:B")
        self.assertEqual(
            {b.question_id for b in decision.judgment_bindings},
            {"route-risk:A", "route-risk:B", "should-disengage"},
        )
        self.assertEqual(decision.policy_config_key, POLICY_CONFIG.key)
        self.assertEqual(decision.semantic_input_key, semantic_snapshot_key(state))

    def test_direct_policy_bundle_construction_rejected(self):
        with self.assertRaises(TypeError):
            PolicyUsableJudgmentBundle(
                None, (), 0, object()  # type: ignore[arg-type]
            )

    def test_missing_required_no_authority(self):
        state = snapshot()
        _, plan = self.reduction_plan(state)
        scripts = ambiguous_scripts()
        del scripts["route-risk:B"]
        scheduled = self.scheduler.execute(plan, FakeJEVAdapter(scripts))
        validation = self.validator.validate(state, plan, scheduled.results, now=30)
        self.assertEqual(validation.status, BundleValidationStatus.INVALID)
        self.assertIn(BundleReason.PROVIDER_FAILURE, validation.reasons)
        self.assertIn(BundleReason.MISSING_REQUIRED, validation.reasons)

    def test_score_probability_mismatch_rejected(self):
        state = snapshot()
        _, plan = self.reduction_plan(state)
        scripts = ambiguous_scripts()
        scripts["route-risk:A"] = replace(
            scripts["route-risk:A"], value_kind=ValueKind.SCORE
        )
        validation = self.validator.validate(
            state,
            plan,
            self.scheduler.execute(plan, FakeJEVAdapter(scripts)).results,
            now=30,
        )
        self.assertIn(BundleReason.OUTPUT_KIND_MISMATCH, validation.reasons)

    def test_calibration_provenance_is_substantive(self):
        state = snapshot()
        _, plan = self.reduction_plan(state)
        scripts = ambiguous_scripts()
        bad = replace(
            provenance("route-risk-v1"),
            authority="unknown-authority",
            metric_value=0.2,
        )
        scripts["route-risk:A"] = replace(
            scripts["route-risk:A"], calibration_provenance=bad
        )
        validation = self.validator.validate(
            state,
            plan,
            self.scheduler.execute(plan, FakeJEVAdapter(scripts)).results,
            now=30,
        )
        self.assertIn(BundleReason.CALIBRATION_PROVENANCE_MISMATCH, validation.reasons)

    def test_provider_failure_is_not_stale_evidence(self):
        state = snapshot()
        _, plan = self.reduction_plan(state)
        scripts = ambiguous_scripts()
        scripts["route-risk:A"] = ScriptedAnswer(
            ResultStatus.ERROR,
            completed_at=0,
        )
        validation = self.validator.validate(
            state,
            plan,
            self.scheduler.execute(plan, FakeJEVAdapter(scripts)).results,
            now=30,
        )
        self.assertIn(BundleReason.PROVIDER_FAILURE, validation.reasons)
        self.assertNotIn(BundleReason.RESULT_STALE, validation.reasons)

    def test_validator_owns_evidence_freshness(self):
        state = snapshot()
        _, plan = self.reduction_plan(state)
        scripts = {
            key: replace(value, completed_at=1, fresh_until=999999)
            for key, value in ambiguous_scripts().items()
        }
        validation = JudgmentBundleValidator(
            JudgmentFreshnessPolicy(max_age=5), CAL_POLICY
        ).validate(
            state,
            plan,
            self.scheduler.execute(plan, FakeJEVAdapter(scripts)).results,
            now=30,
        )
        self.assertIn(BundleReason.RESULT_STALE, validation.reasons)

    def test_decision_expiry_checked_before_execution(self):
        state = snapshot()
        reduction, _, _, validation = self.validated(state)
        config = PolicyConfig(decision_ttl=5)
        decision = self.policy.decide(
            state, reduction, validation.validated, config, now=30
        )
        fresh = replace(state, snapshot_id="snapshot-2", state_epoch=2)
        checked = FreshStateValidator().validate(
            decision,
            fresh,
            bundle=validation.validated,
            config=config,
            now=36,
        )
        self.assertEqual(checked.reasons, (FreshValidationReason.DECISION_EXPIRED,))

    def test_consumed_judgment_expiry_checked_before_execution(self):
        state = snapshot()
        short = JudgmentBundleValidator(JudgmentFreshnessPolicy(max_age=15), CAL_POLICY)
        reduction, plan = self.reduction_plan(state)
        scheduled = self.scheduler.execute(plan, FakeJEVAdapter(ambiguous_scripts()))
        validation = short.validate(state, plan, scheduled.results, now=30)
        decision = self.policy.decide(
            state, reduction, validation.validated, POLICY_CONFIG, now=30
        )
        fresh = replace(state, snapshot_id="snapshot-2", state_epoch=2)
        checked = FreshStateValidator().validate(
            decision,
            fresh,
            bundle=validation.validated,
            config=POLICY_CONFIG,
            now=36,
        )
        self.assertEqual(
            checked.reasons,
            (FreshValidationReason.JUDGMENT_EVIDENCE_EXPIRED,),
        )

    def test_policy_config_change_invalidates_decision(self):
        state = snapshot()
        reduction, _, _, validation = self.validated(state)
        decision = self.policy.decide(
            state, reduction, validation.validated, POLICY_CONFIG, now=30
        )
        fresh = replace(state, snapshot_id="snapshot-2", state_epoch=2)
        checked = FreshStateValidator().validate(
            decision,
            fresh,
            bundle=validation.validated,
            config=PolicyConfig(disengage_threshold=0.7, decision_ttl=50),
            now=40,
        )
        self.assertEqual(checked.reasons, (FreshValidationReason.POLICY_CONFIG_CHANGED,))

    def test_judgment_identity_or_value_change_invalidates_decision(self):
        state = snapshot()
        reduction, plan, _, validation = self.validated(state)
        decision = self.policy.decide(
            state, reduction, validation.validated, POLICY_CONFIG, now=30
        )
        changed_scripts = ambiguous_scripts()
        changed_scripts["route-risk:B"] = replace(
            changed_scripts["route-risk:B"], value=0.21
        )
        changed_validation = self.validator.validate(
            state,
            plan,
            self.scheduler.execute(plan, FakeJEVAdapter(changed_scripts)).results,
            now=30,
        )
        fresh = replace(state, snapshot_id="snapshot-2", state_epoch=2)
        checked = FreshStateValidator().validate(
            decision,
            fresh,
            bundle=changed_validation.validated,
            config=POLICY_CONFIG,
            now=40,
        )
        self.assertEqual(
            checked.reasons,
            (FreshValidationReason.JUDGMENT_EVIDENCE_CHANGED,),
        )

    def test_semantic_input_change_invalidates_even_unselected_route(self):
        state = snapshot()
        reduction, _, _, validation = self.validated(state)
        decision = self.policy.decide(
            state, reduction, validation.validated, POLICY_CONFIG, now=30
        )
        changed_a = replace(state.routes[0], length=11)
        fresh = replace(
            state,
            snapshot_id="snapshot-2",
            state_epoch=2,
            routes=(changed_a, state.routes[1]),
        )
        checked = FreshStateValidator().validate(
            decision,
            fresh,
            bundle=validation.validated,
            config=POLICY_CONFIG,
            now=40,
        )
        self.assertEqual(
            checked.reasons,
            (FreshValidationReason.SEMANTIC_INPUTS_CHANGED,),
        )

    def test_canonical_snapshot_key_is_stable_under_route_order(self):
        state = snapshot()
        reordered = replace(state, routes=tuple(reversed(state.routes)))
        self.assertEqual(semantic_snapshot_key(state), semantic_snapshot_key(reordered))

    def test_epoch_change_rejects_execution(self):
        state = snapshot()
        reduction, _, _, validation = self.validated(state)
        decision = self.policy.decide(
            state, reduction, validation.validated, POLICY_CONFIG, now=30
        )
        fresh = replace(
            state,
            snapshot_id="snapshot-2",
            observation_epoch=8,
            state_epoch=2,
        )
        checked = FreshStateValidator().validate(
            decision,
            fresh,
            bundle=validation.validated,
            config=POLICY_CONFIG,
            now=40,
        )
        self.assertEqual(
            checked.reasons,
            (FreshValidationReason.OBSERVATION_EPOCH_CHANGED,),
        )

    def test_correlated_probability_fusion_is_forbidden(self):
        state = snapshot()
        _, plan, scheduled, _ = self.validated(state)
        with self.assertRaisesRegex(ValueError, "correlated"):
            ProbabilityFusion.product(
                plan.questions,
                scheduled.results,
                independence_justification="synthetic",
            )

    def test_reuse_requires_full_compatibility(self):
        state = snapshot()
        _, plan, scheduled, _ = self.validated(state)
        question = plan.questions[0]
        result = scheduled.results[0]
        self.assertTrue(
            reuse_allowed(
                question,
                result,
                now=30,
                freshness=FRESHNESS,
                provider_id="fake-provider",
                model_id="fake-model",
                observation_epoch=state.observation_epoch,
                allow_cross_snapshot=True,
            )
        )
        changed = snapshot(snapshot_id="snapshot-2", risk_tolerance=0.6)
        _, changed_plan = self.reduction_plan(changed)
        changed_question = changed_plan.questions[0]
        self.assertEqual(
            judgment_equivalence_key(question),
            judgment_equivalence_key(changed_question),
        )
        self.assertNotEqual(
            judgment_dependency_key(question),
            judgment_dependency_key(changed_question),
        )
        self.assertFalse(
            reuse_allowed(
                changed_question,
                result,
                now=30,
                freshness=FRESHNESS,
                provider_id="fake-provider",
                model_id="fake-model",
                observation_epoch=changed.observation_epoch,
                allow_cross_snapshot=True,
            )
        )
        self.assertFalse(
            reuse_allowed(
                question,
                result,
                now=30,
                freshness=FRESHNESS,
                provider_id="other-provider",
                model_id="fake-model",
                observation_epoch=state.observation_epoch,
                allow_cross_snapshot=True,
            )
        )
        self.assertFalse(
            reuse_allowed(
                question,
                result,
                now=999,
                freshness=FRESHNESS,
                provider_id="fake-provider",
                model_id="fake-model",
                observation_epoch=state.observation_epoch,
                allow_cross_snapshot=True,
            )
        )

    def test_optional_short_circuit_cancels_outstanding_optional_work(self):
        state = snapshot()
        reduction, plan = self.reduction_plan(state, optional=True)
        scheduled = self.scheduler.execute_until_policy_sufficient(
            plan,
            FakeJEVAdapter(ambiguous_scripts(optional_block=True)),
            sufficient=lambda results: all(
                result.status is ResultStatus.ANSWERED for result in results
            ),
        )
        self.assertEqual(scheduled.cancelled_optional, ("optional-context-note",))
        validation = self.validator.validate(
            state, plan, scheduled.results, now=30, allow_missing_optional=True
        )
        self.assertEqual(validation.status, BundleValidationStatus.PARTIAL)
        decision = self.policy.decide(
            state, reduction, validation.validated, POLICY_CONFIG, now=30
        )
        self.assertEqual(decision.selected_action.candidate_id, "TAKE_ROUTE:B")

    def _fresh_validated_decision(self):
        state = snapshot()
        reduction, _, scheduled, validation = self.validated(state)
        decision = self.policy.decide(
            state, reduction, validation.validated, POLICY_CONFIG, now=30
        )
        fresh = replace(state, snapshot_id="snapshot-2", state_epoch=2)
        checked = FreshStateValidator().validate(
            decision,
            fresh,
            bundle=validation.validated,
            config=POLICY_CONFIG,
            now=40,
        )
        self.assertTrue(checked.valid)
        return state, reduction, scheduled, validation, decision, checked

    def test_pending_intent_duplicate_and_resource_conflict(self):
        _, _, _, _, _, checked = self._fresh_validated_decision()
        registry = PendingIntentRegistry()
        first = registry.admit(checked.decision)
        self.assertEqual(first.status, IntentAdmissionStatus.ADMITTED)
        duplicate = registry.admit(checked.decision)
        self.assertEqual(
            duplicate.status,
            IntentAdmissionStatus.DUPLICATE_PENDING_INTENT,
        )

        retreat_decision = replace(
            checked.decision,
            action=replace(
                checked.decision.action,
                candidate_id="RETREAT:safe-harbor",
                kind=checked.decision.action.kind.RETREAT,
                route_id=None,
                destination_id="safe-harbor",
            ),
            resource_claims=("navigation",),
        )
        busy = registry.admit(retreat_decision)
        self.assertEqual(busy.status, IntentAdmissionStatus.RESOURCE_BUSY)

        registry.resolve(first.pending.intent_id)
        admitted = registry.admit(retreat_decision)
        self.assertEqual(admitted.status, IntentAdmissionStatus.ADMITTED)

    def test_delivery_not_final_effect_and_verified_success(self):
        _, _, _, _, _, checked = self._fresh_validated_decision()
        registry = PendingIntentRegistry()
        admission = registry.admit(checked.decision)
        plan = SimulatedActionCompiler().compile(checked.decision, admission)
        executor = SimulatedExecutor()
        incomplete = OutcomeVerifier().verify(
            executor.dispatch(
                plan,
                command_accepted=False,
                progressing=False,
                final_effect=False,
            )
        )
        self.assertFalse(incomplete.success)
        self.assertEqual(incomplete.highest_stage, OutcomeStage.DELIVERED)
        complete = OutcomeVerifier().verify(
            executor.dispatch(
                plan,
                command_accepted=True,
                progressing=True,
                final_effect=True,
            )
        )
        self.assertTrue(complete.success)
        self.assertEqual(complete.highest_stage, OutcomeStage.FINAL_EFFECT)

    def test_trace_replay_reproduces_policy_causality(self):
        state = snapshot()
        reduction, plan, scheduled, validation = self.validated(state)
        decision = self.policy.decide(
            state, reduction, validation.validated, POLICY_CONFIG, now=30
        )
        fresh = replace(state, snapshot_id="snapshot-2", state_epoch=2)
        fresh_validation = FreshStateValidator().validate(
            decision,
            fresh,
            bundle=validation.validated,
            config=POLICY_CONFIG,
            now=40,
        )
        registry = PendingIntentRegistry()
        admission = registry.admit(fresh_validation.decision)
        exec_plan = SimulatedActionCompiler().compile(
            fresh_validation.decision,
            admission,
        )
        outcome = OutcomeVerifier().verify(
            SimulatedExecutor().dispatch(
                exec_plan,
                command_accepted=True,
                progressing=True,
                final_effect=True,
            )
        )
        trace = TraceRecorder.record(
            snapshot=state,
            reduction=reduction,
            plan=plan,
            scheduled=scheduled,
            validation=validation,
            freshness=FRESHNESS,
            calibration_policy=CAL_POLICY,
            policy_config=POLICY_CONFIG,
            decision=decision,
            fresh_validation=fresh_validation,
            execution_plan=exec_plan,
            outcome=outcome,
        )
        replayed = ReplayRunner().replay(
            trace,
            calibration_policy=CAL_POLICY,
            policy_config=POLICY_CONFIG,
            now=30,
        )
        self.assertEqual(replayed, decision)
        with self.assertRaisesRegex(ValueError, "policy config"):
            ReplayRunner().replay(
                trace,
                calibration_policy=CAL_POLICY,
                policy_config=PolicyConfig(disengage_threshold=0.7, decision_ttl=50),
                now=30,
            )


if __name__ == "__main__":
    unittest.main()
