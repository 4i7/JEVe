from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jeve.model import (
    BundleReason,
    BundleValidationStatus,
    CalibrationStatus,
    HardConstraints,
    Knowledge,
    KnowledgeStatus,
    Objective,
    OutcomeStage,
    PolicyStatus,
    ReductionReason,
    ResultStatus,
    RouteState,
    StateSnapshot,
    ValueKind,
)
from jeve.pipeline import (
    BundleValidationPolicy,
    CandidateGenerator,
    DeterministicPolicy,
    DeterministicReducer,
    FakeJEVAdapter,
    FreshStateValidator,
    JudgmentBundleValidator,
    JudgmentPlanner,
    JudgmentScheduler,
    OutcomeVerifier,
    PolicyConfig,
    ScriptedAnswer,
    SimulatedActionCompiler,
    SimulatedExecutor,
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
    fresh_until: int = 100,
    routes: tuple[RouteState, ...] | None = None,
    constraints: HardConstraints | None = None,
    retreat_available: Knowledge[bool] | None = None,
    exact_should_disengage: Knowledge[float] | None = None,
) -> StateSnapshot:
    return StateSnapshot(
        snapshot_id=snapshot_id,
        observation_epoch=observation_epoch,
        state_epoch=state_epoch,
        observed_at=10,
        fresh_until=fresh_until,
        objective=Objective(destination_id="destination", risk_tolerance=0.50),
        constraints=constraints or HardConstraints(),
        routes=routes
        or (
            route("A", length=10),
            route("B", length=15),
        ),
        retreat_destination_id="safe-harbor",
        retreat_available=retreat_available or Knowledge.known(True),
        exact_should_disengage=exact_should_disengage or Knowledge.unknown(),
    )


def ambiguous_scripts(*, fresh_until: int = 100) -> dict[str, ScriptedAnswer]:
    return {
        "route-risk:A": ScriptedAnswer(
            ResultStatus.ANSWERED,
            ValueKind.PROBABILITY,
            0.72,
            CalibrationStatus.CALIBRATED,
            completed_at=20,
            fresh_until=fresh_until,
        ),
        "route-risk:B": ScriptedAnswer(
            ResultStatus.ANSWERED,
            ValueKind.PROBABILITY,
            0.22,
            CalibrationStatus.CALIBRATED,
            completed_at=20,
            fresh_until=fresh_until,
        ),
        "should-disengage": ScriptedAnswer(
            ResultStatus.ANSWERED,
            ValueKind.PROBABILITY,
            0.15,
            CalibrationStatus.CALIBRATED,
            completed_at=20,
            fresh_until=fresh_until,
        ),
    }


class ArchitectureSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = CandidateGenerator()
        self.reducer = DeterministicReducer()
        self.planner = JudgmentPlanner()
        self.scheduler = JudgmentScheduler()
        self.bundle_validator = JudgmentBundleValidator()
        self.policy = DeterministicPolicy()

    def _reduction_and_plan(self, state: StateSnapshot):
        candidates = self.generator.generate(state)
        reduction = self.reducer.reduce(state, candidates)
        plan = self.planner.plan(state, reduction)
        return reduction, plan

    def _validated_ambiguous_bundle(self, state: StateSnapshot):
        reduction, plan = self._reduction_and_plan(state)
        adapter = FakeJEVAdapter(ambiguous_scripts())
        scheduled = self.scheduler.execute(plan, adapter)
        validation = self.bundle_validator.validate(
            state,
            plan,
            scheduled.results,
            BundleValidationPolicy(now=30),
        )
        self.assertIsNotNone(validation.validated)
        return reduction, plan, scheduled, validation.validated, adapter

    def test_knowledge_states_remain_distinct(self) -> None:
        known_false = Knowledge.known(False)
        unknown = Knowledge.unknown()
        stale = Knowledge.stale()
        transitional = Knowledge.transitional()

        self.assertEqual(known_false.status, KnowledgeStatus.KNOWN)
        self.assertIs(known_false.value, False)
        self.assertEqual(unknown.status, KnowledgeStatus.UNKNOWN)
        self.assertEqual(stale.status, KnowledgeStatus.STALE)
        self.assertEqual(transitional.status, KnowledgeStatus.TRANSITIONAL)
        self.assertNotEqual(unknown, stale)
        self.assertNotEqual(stale, transitional)

    def test_reducer_emits_stable_reason_codes(self) -> None:
        state = snapshot(
            routes=(
                route(
                    "invalid",
                    reachable=Knowledge.known(False),
                    length=4,
                    exact_risk=Knowledge.known(0.10),
                ),
                route(
                    "unavailable",
                    length=4,
                    available=False,
                    exact_risk=Knowledge.known(0.10),
                ),
                route(
                    "too-long",
                    length=50,
                    exact_risk=Knowledge.known(0.10),
                ),
                route(
                    "best",
                    length=5,
                    exact_risk=Knowledge.known(0.10),
                ),
                route(
                    "dominated",
                    length=8,
                    exact_risk=Knowledge.known(0.10),
                ),
            ),
            constraints=HardConstraints(max_route_length=20),
            retreat_available=Knowledge.known(False),
            exact_should_disengage=Knowledge.known(0.0),
        )
        reduction, _ = self._reduction_and_plan(state)
        reason_by_candidate = {
            item.candidate_id: item.reason for item in reduction.eliminated
        }

        self.assertEqual(
            reason_by_candidate["TAKE_ROUTE:invalid"],
            ReductionReason.INVALID_PRECONDITION,
        )
        self.assertEqual(
            reason_by_candidate["TAKE_ROUTE:unavailable"],
            ReductionReason.UNAVAILABLE_ACTION,
        )
        self.assertEqual(
            reason_by_candidate["TAKE_ROUTE:too-long"],
            ReductionReason.HARD_CONSTRAINT_VIOLATION,
        )
        self.assertEqual(
            reason_by_candidate["TAKE_ROUTE:dominated"],
            ReductionReason.STRICTLY_DOMINATED_EXACT_OPTION,
        )

    def test_fixture_1_deterministic_only_uses_zero_jev_calls(self) -> None:
        state = snapshot(
            routes=(
                route(
                    "A",
                    length=10,
                    exact_risk=Knowledge.known(0.20),
                ),
                route(
                    "B",
                    length=15,
                    exact_risk=Knowledge.known(0.20),
                ),
            ),
            retreat_available=Knowledge.known(False),
            exact_should_disengage=Knowledge.known(0.0),
        )
        reduction, plan = self._reduction_and_plan(state)
        adapter = FakeJEVAdapter({})
        scheduled = self.scheduler.execute(plan, adapter)

        self.assertEqual(plan.questions, ())
        self.assertEqual(scheduled.waves, ())
        self.assertEqual(adapter.call_count, 0)

        decision = self.policy.decide(
            state,
            reduction,
            bundle=None,
            config=PolicyConfig(),
        )
        self.assertEqual(decision.status, PolicyStatus.SELECTED)
        self.assertEqual(decision.selected_action.candidate_id, "TAKE_ROUTE:A")

    def test_fixture_2_parallel_route_risk_is_one_wave_and_policy_selects_semantic_action(
        self,
    ) -> None:
        state = snapshot()
        reduction, plan = self._reduction_and_plan(state)

        self.assertEqual(
            tuple(question.question_id for question in plan.questions),
            ("route-risk:A", "route-risk:B", "should-disengage"),
        )

        adapter = FakeJEVAdapter(ambiguous_scripts())
        scheduled = self.scheduler.execute(plan, adapter)

        self.assertEqual(
            scheduled.waves,
            (("route-risk:A", "route-risk:B", "should-disengage"),),
        )
        self.assertEqual(adapter.call_count, 3)

        validation = self.bundle_validator.validate(
            state,
            plan,
            scheduled.results,
            BundleValidationPolicy(now=30),
        )
        self.assertEqual(validation.status, BundleValidationStatus.VALID)

        decision = self.policy.decide(
            state,
            reduction,
            validation.validated,
            PolicyConfig(),
        )
        self.assertEqual(decision.status, PolicyStatus.SELECTED)
        self.assertEqual(decision.selected_action.candidate_id, "TAKE_ROUTE:B")

    def test_fixture_3_missing_required_judgment_has_no_action_authority(self) -> None:
        state = snapshot()
        _, plan = self._reduction_and_plan(state)
        scripts = ambiguous_scripts()
        del scripts["route-risk:B"]

        scheduled = self.scheduler.execute(plan, FakeJEVAdapter(scripts))
        validation = self.bundle_validator.validate(
            state,
            plan,
            scheduled.results,
            BundleValidationPolicy(now=30),
        )

        self.assertEqual(validation.status, BundleValidationStatus.INVALID)
        self.assertIn(BundleReason.MISSING_REQUIRED, validation.reasons)
        self.assertIsNone(validation.validated)

    def test_fixture_4_invalid_semantic_output_is_rejected(self) -> None:
        state = snapshot()
        _, plan = self._reduction_and_plan(state)
        scripts = ambiguous_scripts()
        scripts["route-risk:A"] = ScriptedAnswer(
            ResultStatus.ANSWERED,
            ValueKind.SCORE,
            0.30,
            CalibrationStatus.CALIBRATED,
            completed_at=20,
            fresh_until=100,
        )

        scheduled = self.scheduler.execute(plan, FakeJEVAdapter(scripts))
        validation = self.bundle_validator.validate(
            state,
            plan,
            scheduled.results,
            BundleValidationPolicy(now=30),
        )

        self.assertEqual(validation.status, BundleValidationStatus.INVALID)
        self.assertIn(BundleReason.OUTPUT_KIND_MISMATCH, validation.reasons)
        self.assertIsNone(validation.validated)

    def test_fixture_5_calibration_requirement_rejects_uncalibrated_probability(
        self,
    ) -> None:
        state = snapshot()
        _, plan = self._reduction_and_plan(state)
        scripts = ambiguous_scripts()
        scripts["route-risk:A"] = ScriptedAnswer(
            ResultStatus.ANSWERED,
            ValueKind.PROBABILITY,
            0.30,
            CalibrationStatus.UNCALIBRATED,
            completed_at=20,
            fresh_until=100,
        )

        scheduled = self.scheduler.execute(plan, FakeJEVAdapter(scripts))
        validation = self.bundle_validator.validate(
            state,
            plan,
            scheduled.results,
            BundleValidationPolicy(now=30),
        )

        self.assertEqual(validation.status, BundleValidationStatus.INVALID)
        self.assertIn(BundleReason.CALIBRATION_INSUFFICIENT, validation.reasons)
        self.assertIsNone(validation.validated)

    def test_fixture_6_stale_bundle_cannot_enter_policy(self) -> None:
        state = snapshot()
        _, plan = self._reduction_and_plan(state)
        adapter = FakeJEVAdapter(ambiguous_scripts(fresh_until=25))
        scheduled = self.scheduler.execute(plan, adapter)

        validation = self.bundle_validator.validate(
            state,
            plan,
            scheduled.results,
            BundleValidationPolicy(now=30),
        )

        self.assertEqual(validation.status, BundleValidationStatus.STALE)
        self.assertIn(BundleReason.RESULT_STALE, validation.reasons)
        self.assertIsNone(validation.validated)

    def test_fixture_7_epoch_change_after_policy_rejects_execution(self) -> None:
        state = snapshot()
        reduction, _, _, bundle, _ = self._validated_ambiguous_bundle(state)
        decision = self.policy.decide(
            state,
            reduction,
            bundle,
            PolicyConfig(),
        )
        self.assertEqual(decision.status, PolicyStatus.SELECTED)

        fresh = replace(
            state,
            snapshot_id="snapshot-2",
            observation_epoch=8,
            state_epoch=2,
        )
        validation = FreshStateValidator().validate(decision, fresh, now=40)

        self.assertFalse(validation.valid)
        self.assertEqual(
            validation.reasons[0].value,
            "OBSERVATION_EPOCH_CHANGED",
        )
        self.assertIsNone(validation.decision)

    def test_fresh_validation_rejects_precondition_and_constraint_changes(self) -> None:
        state = snapshot()
        reduction, _, _, bundle, _ = self._validated_ambiguous_bundle(state)
        decision = self.policy.decide(state, reduction, bundle, PolicyConfig())
        self.assertEqual(decision.selected_action.candidate_id, "TAKE_ROUTE:B")

        route_b_unreachable = replace(
            state.routes[1],
            reachable=Knowledge.known(False),
        )
        precondition_changed = replace(
            state,
            snapshot_id="snapshot-2",
            state_epoch=2,
            routes=(state.routes[0], route_b_unreachable),
        )
        precondition_validation = FreshStateValidator().validate(
            decision,
            precondition_changed,
            now=40,
        )
        self.assertFalse(precondition_validation.valid)
        self.assertEqual(
            precondition_validation.reasons[0].value,
            "REQUIRED_PRECONDITION_NO_LONGER_HOLDS",
        )

        constraint_changed = replace(
            state,
            snapshot_id="snapshot-3",
            state_epoch=3,
            constraints=HardConstraints(max_route_length=12),
        )
        constraint_validation = FreshStateValidator().validate(
            decision,
            constraint_changed,
            now=40,
        )
        self.assertFalse(constraint_validation.valid)
        self.assertEqual(
            constraint_validation.reasons[0].value,
            "HARD_CONSTRAINT_CHANGED_INCOMPATIBLY",
        )

    def _compiled_selected_route(self):
        state = snapshot()
        reduction, _, _, bundle, _ = self._validated_ambiguous_bundle(state)
        decision = self.policy.decide(state, reduction, bundle, PolicyConfig())
        fresh = replace(state, snapshot_id="snapshot-2", state_epoch=2)
        fresh_validation = FreshStateValidator().validate(decision, fresh, now=40)
        self.assertTrue(fresh_validation.valid)
        return SimulatedActionCompiler().compile(fresh_validation.decision)

    def test_fixture_8_delivered_does_not_mean_final_effect(self) -> None:
        plan = self._compiled_selected_route()
        evidence = SimulatedExecutor().dispatch(
            plan,
            command_accepted=False,
            progressing=False,
            final_effect=False,
        )
        verification = OutcomeVerifier().verify(evidence)

        self.assertTrue(evidence.delivered)
        self.assertFalse(verification.success)
        self.assertEqual(verification.highest_stage, OutcomeStage.DELIVERED)

    def test_fixture_9_success_requires_verified_final_effect(self) -> None:
        plan = self._compiled_selected_route()
        evidence = SimulatedExecutor().dispatch(
            plan,
            command_accepted=True,
            progressing=True,
            final_effect=True,
        )
        verification = OutcomeVerifier().verify(evidence)

        self.assertTrue(verification.success)
        self.assertEqual(verification.highest_stage, OutcomeStage.FINAL_EFFECT)


if __name__ == "__main__":
    unittest.main()
