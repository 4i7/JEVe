from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Mapping

from .model import (
    CalibrationStatus,
    JudgmentPlan,
    JudgmentQuestion,
    JudgmentResult,
    PolicyDecision,
    ResultStatus,
    StateSnapshot,
    ValidatedJudgmentBundle,
)
from .pipeline import (
    BundleValidationPolicy,
    DeterministicPolicy,
    FakeJEVAdapter,
    FreshStateValidator,
    JudgmentBundleValidator,
    PolicyConfig,
    ScheduledJudgments,
)


@dataclass(frozen=True)
class CalibrationEvidence:
    """Why a CALIBRATED claim is allowed to enter policy.

    This is intentionally small. The architecture only needs an explicit,
    inspectable basis rather than accepting the enum value by itself.
    """

    authority: str
    basis: str

    def __post_init__(self) -> None:
        if not self.authority.strip() or not self.basis.strip():
            raise ValueError("calibration evidence requires authority and basis")


@dataclass(frozen=True)
class EvidenceEnvelope:
    result: JudgmentResult
    equivalence_key: str
    correlation_key: str | None
    calibration_evidence: CalibrationEvidence | None = None


@dataclass(frozen=True)
class JudgmentFreshnessPolicy:
    """Validator-owned judgment freshness policy.

    Providers report completion time. They do not decide how long semantic
    evidence remains policy-usable.
    """

    max_age: int

    def __post_init__(self) -> None:
        if self.max_age < 0:
            raise ValueError("max_age must be non-negative")


class GuardReason:
    EQUIVALENCE_KEY_MISMATCH = "EQUIVALENCE_KEY_MISMATCH"
    CALIBRATION_EVIDENCE_MISSING = "CALIBRATION_EVIDENCE_MISSING"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    SEMANTIC_INPUTS_CHANGED = "SEMANTIC_INPUTS_CHANGED"


_BUNDLE_SEAL = object()


class PolicyUsableJudgmentBundle:
    """Capability wrapper issued only after validation guards pass.

    Python is not a security boundary, so this is protection against accidental
    construction, not against a hostile caller using reflection/private names.
    """

    __slots__ = ("_validated", "_envelopes")

    def __init__(
        self,
        validated: ValidatedJudgmentBundle,
        envelopes: tuple[EvidenceEnvelope, ...],
        seal: object,
    ) -> None:
        if seal is not _BUNDLE_SEAL:
            raise TypeError("PolicyUsableJudgmentBundle is issued by EvidenceAuthority")
        self._validated = validated
        self._envelopes = envelopes

    @property
    def validated(self) -> ValidatedJudgmentBundle:
        return self._validated

    @property
    def envelopes(self) -> tuple[EvidenceEnvelope, ...]:
        return self._envelopes


@dataclass(frozen=True)
class GuardValidation:
    valid: bool
    reasons: tuple[str, ...]
    bundle: PolicyUsableJudgmentBundle | None


def judgment_equivalence_key(question: JudgmentQuestion) -> str:
    """Conservative key for semantic-input equivalence of one judgment.

    Reuse is not enabled by this helper. It only gives reuse a concrete
    prerequisite that includes semantic meaning, feature projection and output
    contract rather than relying on question id or prompt text.
    """

    contract = question.output_contract
    material = repr(
        (
            question.judgment_type,
            question.subject_id,
            question.feature_slice,
            contract.value_kind.value,
            contract.semantics,
            contract.numeric_range,
            contract.calibration_requirement.value,
            contract.abstention_allowed,
        )
    ).encode("utf-8")
    return sha256(material).hexdigest()


def judgment_correlation_key(question: JudgmentQuestion) -> str | None:
    """Declare shared semantic context without implying statistical independence."""

    if question.judgment_type in {"ROUTE_RISK", "SHOULD_DISENGAGE"}:
        return "current-route-risk-context"
    return None


def semantic_snapshot_key(snapshot: StateSnapshot) -> str:
    """Conservative fingerprint of all normalized semantic policy inputs.

    Identity/time fields are intentionally excluded; semantic state is included.
    A future dependency model may safely make this finer grained. Until then,
    any normalized semantic change invalidates a selected decision.
    """

    material = repr(
        (
            snapshot.objective,
            snapshot.constraints,
            snapshot.routes,
            snapshot.retreat_destination_id,
            snapshot.retreat_available,
            snapshot.exact_should_disengage,
        )
    ).encode("utf-8")
    return sha256(material).hexdigest()


class EvidenceAuthority:
    """Owns policy usability of JEV evidence for this draft.

    The provider supplies a result and completion time. This authority owns
    freshness duration, correlation/equivalence checks and calibration basis.
    """

    def __init__(self, freshness: JudgmentFreshnessPolicy) -> None:
        self._freshness = freshness
        self._base = JudgmentBundleValidator()

    def validate(
        self,
        snapshot: StateSnapshot,
        plan: JudgmentPlan,
        envelopes: tuple[EvidenceEnvelope, ...],
        *,
        now: int,
    ) -> GuardValidation:
        question_by_id = {q.question_id: q for q in plan.questions}
        reasons: list[str] = []
        normalized_results: list[JudgmentResult] = []

        for envelope in envelopes:
            result = envelope.result
            question = question_by_id.get(result.question_id)
            if question is None:
                normalized_results.append(result)
                continue

            if envelope.equivalence_key != judgment_equivalence_key(question):
                reasons.append(GuardReason.EQUIVALENCE_KEY_MISMATCH)

            if result.status is ResultStatus.ERROR:
                reasons.append(GuardReason.PROVIDER_FAILURE)
            elif (
                result.status is ResultStatus.ANSWERED
                and result.calibration is CalibrationStatus.CALIBRATED
                and envelope.calibration_evidence is None
            ):
                reasons.append(GuardReason.CALIBRATION_EVIDENCE_MISSING)

            # Provider fresh_until is deliberately ignored. The validator owns
            # semantic evidence lifetime in this draft.
            normalized_results.append(
                replace(
                    result,
                    fresh_until=result.completed_at + self._freshness.max_age,
                )
            )

        base = self._base.validate(
            snapshot,
            plan,
            tuple(normalized_results),
            BundleValidationPolicy(now=now),
        )
        reasons.extend(reason.value for reason in base.reasons)
        unique = tuple(dict.fromkeys(reasons))

        if unique or base.validated is None:
            return GuardValidation(False, unique, None)

        return GuardValidation(
            True,
            (),
            PolicyUsableJudgmentBundle(base.validated, envelopes, _BUNDLE_SEAL),
        )

    @staticmethod
    def envelope(
        question: JudgmentQuestion,
        result: JudgmentResult,
        calibration_evidence: CalibrationEvidence | None = None,
    ) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            result=result,
            equivalence_key=judgment_equivalence_key(question),
            correlation_key=judgment_correlation_key(question),
            calibration_evidence=calibration_evidence,
        )


class ConcurrentJudgmentScheduler:
    """Execute each dependency wave concurrently while preserving result order."""

    def execute(
        self,
        plan: JudgmentPlan,
        adapter: FakeJEVAdapter,
    ) -> ScheduledJudgments:
        from .pipeline import JudgmentScheduler

        waves = JudgmentScheduler().build_waves(plan)
        question_by_id = {q.question_id: q for q in plan.questions}
        result_by_id: dict[str, JudgmentResult] = {}

        for wave in waves:
            with ThreadPoolExecutor(max_workers=max(1, len(wave))) as executor:
                futures = {
                    question_id: executor.submit(
                        adapter.evaluate,
                        plan,
                        question_by_id[question_id],
                    )
                    for question_id in wave
                }
                for question_id in wave:
                    result_by_id[question_id] = futures[question_id].result()

        ordered = tuple(
            result_by_id[q.question_id]
            for q in plan.questions
            if q.question_id in result_by_id
        )
        return ScheduledJudgments(waves=waves, results=ordered)


@dataclass(frozen=True)
class BoundPolicyDecision:
    decision: PolicyDecision
    semantic_input_key: str
    judgment_equivalence_keys: tuple[tuple[str, str], ...]


class BoundDeterministicPolicy:
    """Policy wrapper that records the semantic inputs its decision depended on."""

    def __init__(self) -> None:
        self._policy = DeterministicPolicy()

    def decide(
        self,
        snapshot: StateSnapshot,
        reduction,
        bundle: PolicyUsableJudgmentBundle | None,
        config: PolicyConfig,
    ) -> BoundPolicyDecision:
        decision = self._policy.decide(
            snapshot,
            reduction,
            None if bundle is None else bundle.validated,
            config,
        )
        bindings = () if bundle is None else tuple(
            (envelope.result.question_id, envelope.equivalence_key)
            for envelope in bundle.envelopes
        )
        return BoundPolicyDecision(
            decision=decision,
            semantic_input_key=semantic_snapshot_key(snapshot),
            judgment_equivalence_keys=bindings,
        )


class BoundFreshStateValidator:
    """Reject rather than repair when any policy semantic input changed."""

    def __init__(self) -> None:
        self._base = FreshStateValidator()

    def validate(
        self,
        bound: BoundPolicyDecision,
        fresh_snapshot: StateSnapshot,
        *,
        now: int,
    ):
        if semantic_snapshot_key(fresh_snapshot) != bound.semantic_input_key:
            from .model import FreshValidation

            return FreshValidation(
                False,
                (GuardReason.SEMANTIC_INPUTS_CHANGED,),  # draft reason is intentionally stable text
                None,
            )
        return self._base.validate(bound.decision, fresh_snapshot, now)


def reuse_allowed(
    question: JudgmentQuestion,
    envelope: EvidenceEnvelope,
    *,
    allow_cross_snapshot: bool = False,
) -> bool:
    """Fail closed on reuse unless semantic equivalence is explicit.

    Cross-snapshot reuse remains disabled by default even when the key matches.
    """

    if envelope.equivalence_key != judgment_equivalence_key(question):
        return False
    return allow_cross_snapshot
