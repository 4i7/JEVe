from __future__ import annotations

import sys
import threading
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jeve.model import (
    CalibrationStatus,
    HardConstraints,
    Knowledge,
    Objective,
    PolicyStatus,
    ResultStatus,
    RouteState,
    StateSnapshot,
    ValueKind,
)
from jeve.pipeline import (
    CandidateGenerator,
    DeterministicReducer,
    FakeJEVAdapter,
    JudgmentPlanner,
    PolicyConfig,
    ScriptedAnswer,
)
from jeve.validation_guards import (
    BoundDeterministicPolicy,
    BoundFreshStateValidator,
    CalibrationEvidence,
    ConcurrentJudgmentScheduler,
    EvidenceAuthority,
    EvidenceEnvelope,
    GuardReason,
    JudgmentFreshnessPolicy,
    PolicyUsableJudgmentBundle,
    judgment_correlation_key,
    judgment_equivalence_key,
    reuse_allowed,
)


def route(route_id: str, length: int) -> RouteState:
    return RouteState(
        route_id=route_id,
        reachable=Knowledge.known(True),
        length=length,
        available=True,
        exact_risk=Knowledge.unknown(),
    )


def state() -> StateSnapshot:
    return StateSnapshot(
        snapshot_id="snapshot-1",
        observation_epoch=7,
        state_epoch=1,
        observed_at=10,
        fresh_until=100,
        objective=Objective(destination_id="destination", risk_tolerance=0.50),
        constraints=HardConstraints(),
        routes=(route("A", 10), route("B", 15)),
        retreat_destination_id="safe-harbor",
        retreat_available=Knowledge.known(True),
        exact_should_disengage=Knowledge.unknown(),
    )


def scripts(*, provider_fresh_until: int = 999) -> dict[str, ScriptedAnswer]:
    return {
        "route-risk:A": ScriptedAnswer(
            ResultStatus.ANSWERED,
            ValueKind.PROBABILITY,
            0.72,
            CalibrationStatus.CALIBRATED,
            completed_at=20,
            fresh_until=provider_fresh_until,
        ),
        "route-risk:B": ScriptedAnswer(
            ResultStatus.ANSWERED,
            ValueKind.PROBABILITY,
            0.22,
            CalibrationStatus.CALIBRATED,
            completed_at=20,
            fresh_until=provider_fresh_until,
        ),
        "should-disengage": ScriptedAnswer(
            ResultStatus.ANSWERED,
            ValueKind.PROBABILITY,
            0.15,
            CalibrationStatus.CALIBRATED,
            completed_at=20,
            fresh_until=provider_fresh_until,
        ),
    }


def plan_and_reduction(snapshot: StateSnapshot):
    generator = CandidateGenerator()
    reducer = DeterministicReducer()
    reduction = reducer.reduce(snapshot, generator.generate(snapshot))
    plan = JudgmentPlanner().plan(snapshot, reduction)
    return reduction, plan


def envelopes(plan, results, *, with_calibration: bool = True):
    question_by_id = {q.question_id: q for q in plan.questions}
    evidence = CalibrationEvidence("fixture", "synthetic calibrated contract")
    return tuple(
        EvidenceAuthority.envelope(
            question_by_id[result.question_id],
            result,
            evidence if with_calibration else None,
        )
        for result in results
    )


class ValidationGuardTests(unittest.TestCase):
    def test_validated_bundle_cannot_be_accidentally_constructed_directly(self) -> None:
        with self.assertRaises(TypeError):
            PolicyUsableJudgmentBundle(None, (), object())  # type: ignore[arg-type]

    def test_calibrated_enum_requires_explicit_calibration_basis(self) -> None:
        snapshot = state()
        _, plan = plan_and_reduction(snapshot)
        scheduled = ConcurrentJudgmentScheduler().execute(plan, FakeJEVAdapter(scripts()))
        validation = EvidenceAuthority(JudgmentFreshnessPolicy(max_age=30)).validate(
            snapshot,
            plan,
            envelopes(plan, scheduled.results, with_calibration=False),
            now=30,
        )
        self.assertFalse(validation.valid)
        self.assertIn(GuardReason.CALIBRATION_EVIDENCE_MISSING, validation.reasons)

    def test_freshness_is_owned_by_validator_not_provider_fresh_until(self) -> None:
        snapshot = state()
        _, plan = plan_and_reduction(snapshot)
        scheduled = ConcurrentJudgmentScheduler().execute(
            plan,
            FakeJEVAdapter(scripts(provider_fresh_until=999999)),
        )
        authority = EvidenceAuthority(JudgmentFreshnessPolicy(max_age=5))
        validation = authority.validate(
            snapshot,
            plan,
            envelopes(plan, scheduled.results),
            now=30,
        )
        self.assertFalse(validation.valid)
        self.assertIn("RESULT_STALE", validation.reasons)

    def test_provider_error_is_not_classified_as_stale_semantic_evidence(self) -> None:
        snapshot = state()
        _, plan = plan_and_reduction(snapshot)
        broken = scripts(provider_fresh_until=0)
        broken["route-risk:A"] = ScriptedAnswer(
            ResultStatus.ERROR,
            completed_at=0,
            fresh_until=0,
        )
        scheduled = ConcurrentJudgmentScheduler().execute(plan, FakeJEVAdapter(broken))
        validation = EvidenceAuthority(JudgmentFreshnessPolicy(max_age=30)).validate(
            snapshot,
            plan,
            envelopes(plan, scheduled.results),
            now=30,
        )
        self.assertFalse(validation.valid)
        self.assertIn(GuardReason.PROVIDER_FAILURE, validation.reasons)
        self.assertNotIn("RESULT_STALE", validation.reasons)

    def test_equivalence_key_is_required_and_cross_snapshot_reuse_is_off_by_default(self) -> None:
        snapshot = state()
        _, plan = plan_and_reduction(snapshot)
        question = plan.questions[0]
        result = ConcurrentJudgmentScheduler().execute(
            plan,
            FakeJEVAdapter(scripts()),
        ).results[0]
        envelope = EvidenceAuthority.envelope(
            question,
            result,
            CalibrationEvidence("fixture", "synthetic calibrated contract"),
        )
        self.assertEqual(envelope.equivalence_key, judgment_equivalence_key(question))
        self.assertFalse(reuse_allowed(question, envelope))
        self.assertTrue(reuse_allowed(question, envelope, allow_cross_snapshot=True))

        wrong = EvidenceEnvelope(
            result=envelope.result,
            equivalence_key="wrong",
            correlation_key=envelope.correlation_key,
            calibration_evidence=envelope.calibration_evidence,
        )
        self.assertFalse(reuse_allowed(question, wrong, allow_cross_snapshot=True))

    def test_correlated_judgments_can_execute_concurrently_without_claiming_independence(self) -> None:
        snapshot = state()
        _, plan = plan_and_reduction(snapshot)
        self.assertEqual(
            {judgment_correlation_key(question) for question in plan.questions},
            {"current-route-risk-context"},
        )

        barrier = threading.Barrier(3)

        class BarrierAdapter(FakeJEVAdapter):
            def evaluate(self, plan, question):
                barrier.wait(timeout=2)
                return super().evaluate(plan, question)

        scheduled = ConcurrentJudgmentScheduler().execute(plan, BarrierAdapter(scripts()))
        self.assertEqual(
            scheduled.waves,
            (("route-risk:A", "route-risk:B", "should-disengage"),),
        )
        self.assertEqual(len(scheduled.results), 3)

    def test_policy_binding_invalidates_on_any_normalized_semantic_input_change(self) -> None:
        snapshot = state()
        reduction, plan = plan_and_reduction(snapshot)
        scheduled = ConcurrentJudgmentScheduler().execute(plan, FakeJEVAdapter(scripts()))
        guarded = EvidenceAuthority(JudgmentFreshnessPolicy(max_age=30)).validate(
            snapshot,
            plan,
            envelopes(plan, scheduled.results),
            now=30,
        )
        self.assertTrue(guarded.valid)

        bound = BoundDeterministicPolicy().decide(
            snapshot,
            reduction,
            guarded.bundle,
            PolicyConfig(),
        )
        self.assertEqual(bound.decision.status, PolicyStatus.SELECTED)
        self.assertEqual(bound.decision.selected_action.candidate_id, "TAKE_ROUTE:B")

        # Route A was not selected, but it was still part of the semantic policy
        # input. The conservative draft therefore invalidates the old decision.
        changed_route_a = replace(snapshot.routes[0], length=11)
        fresh = replace(
            snapshot,
            snapshot_id="snapshot-2",
            state_epoch=2,
            routes=(changed_route_a, snapshot.routes[1]),
        )
        validation = BoundFreshStateValidator().validate(bound, fresh, now=40)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.reasons, (GuardReason.SEMANTIC_INPUTS_CHANGED,))


if __name__ == "__main__":
    unittest.main()
