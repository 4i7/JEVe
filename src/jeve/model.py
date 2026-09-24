from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar


T = TypeVar("T")


class KnowledgeStatus(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"
    TRANSITIONAL = "TRANSITIONAL"


@dataclass(frozen=True)
class Knowledge(Generic[T]):
    status: KnowledgeStatus
    value: T | None = None

    def __post_init__(self) -> None:
        if self.status is KnowledgeStatus.KNOWN and self.value is None:
            raise ValueError("KNOWN knowledge requires a value")
        if self.status is not KnowledgeStatus.KNOWN and self.value is not None:
            raise ValueError(f"{self.status.value} knowledge must not carry a value")

    @classmethod
    def known(cls, value: T) -> "Knowledge[T]":
        return cls(KnowledgeStatus.KNOWN, value)

    @classmethod
    def unknown(cls) -> "Knowledge[T]":
        return cls(KnowledgeStatus.UNKNOWN)

    @classmethod
    def stale(cls) -> "Knowledge[T]":
        return cls(KnowledgeStatus.STALE)

    @classmethod
    def transitional(cls) -> "Knowledge[T]":
        return cls(KnowledgeStatus.TRANSITIONAL)


@dataclass(frozen=True)
class Objective:
    destination_id: str
    risk_tolerance: float


@dataclass(frozen=True)
class HardConstraints:
    max_route_length: int | None = None
    forbidden_route_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteState:
    route_id: str
    reachable: Knowledge[bool]
    length: int
    available: bool
    exact_risk: Knowledge[float]


@dataclass(frozen=True)
class StateSnapshot:
    snapshot_id: str
    observation_epoch: int
    state_epoch: int
    observed_at: int
    fresh_until: int
    objective: Objective
    constraints: HardConstraints
    routes: tuple[RouteState, ...]
    retreat_destination_id: str | None
    retreat_available: Knowledge[bool]
    exact_should_disengage: Knowledge[float]


class ActionKind(str, Enum):
    WAIT = "WAIT"
    TAKE_ROUTE = "TAKE_ROUTE"
    RETREAT = "RETREAT"


@dataclass(frozen=True)
class SemanticAction:
    candidate_id: str
    kind: ActionKind
    route_id: str | None = None
    destination_id: str | None = None

    @classmethod
    def wait(cls) -> "SemanticAction":
        return cls("WAIT", ActionKind.WAIT)

    @classmethod
    def take_route(cls, route_id: str) -> "SemanticAction":
        return cls(f"TAKE_ROUTE:{route_id}", ActionKind.TAKE_ROUTE, route_id=route_id)

    @classmethod
    def retreat(cls, destination_id: str) -> "SemanticAction":
        return cls(
            f"RETREAT:{destination_id}",
            ActionKind.RETREAT,
            destination_id=destination_id,
        )


class ReductionReason(str, Enum):
    INVALID_PRECONDITION = "INVALID_PRECONDITION"
    PRECONDITION_UNRESOLVED = "PRECONDITION_UNRESOLVED"
    HARD_CONSTRAINT_VIOLATION = "HARD_CONSTRAINT_VIOLATION"
    UNAVAILABLE_ACTION = "UNAVAILABLE_ACTION"
    STRICTLY_DOMINATED_EXACT_OPTION = "STRICTLY_DOMINATED_EXACT_OPTION"


@dataclass(frozen=True)
class Elimination:
    candidate_id: str
    reason: ReductionReason


@dataclass(frozen=True)
class ReductionResult:
    surviving_candidates: tuple[SemanticAction, ...]
    eliminated: tuple[Elimination, ...]
    unresolved_dimensions: tuple[str, ...]


class ValueKind(str, Enum):
    PROBABILITY = "PROBABILITY"
    SCORE = "SCORE"


class CalibrationStatus(str, Enum):
    CALIBRATED = "CALIBRATED"
    UNCALIBRATED = "UNCALIBRATED"
    UNKNOWN = "UNKNOWN"


class CalibrationRequirement(str, Enum):
    NONE = "NONE"
    DECLARED = "DECLARED"
    CALIBRATED = "CALIBRATED"


class Criticality(str, Enum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"


class ResultStatus(str, Enum):
    ANSWERED = "ANSWERED"
    ABSTAIN = "ABSTAIN"
    ERROR = "ERROR"


@dataclass(frozen=True)
class JudgmentOutputContract:
    value_kind: ValueKind
    semantics: str
    numeric_range: tuple[float, float]
    calibration_requirement: CalibrationRequirement
    abstention_allowed: bool


@dataclass(frozen=True)
class JudgmentQuestion:
    question_id: str
    judgment_type: str
    subject_id: str
    feature_slice: tuple[tuple[str, str], ...]
    output_contract: JudgmentOutputContract
    criticality: Criticality
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class JudgmentPlan:
    plan_id: str
    snapshot_id: str
    observation_epoch: int
    questions: tuple[JudgmentQuestion, ...]
    required_question_ids: tuple[str, ...]
    optional_question_ids: tuple[str, ...]


@dataclass(frozen=True)
class JudgmentResult:
    question_id: str
    status: ResultStatus
    value_kind: ValueKind | None
    value: float | None
    calibration: CalibrationStatus
    snapshot_id: str
    observation_epoch: int
    completed_at: int
    fresh_until: int


@dataclass(frozen=True)
class JudgmentBundle:
    plan_id: str
    snapshot_id: str
    observation_epoch: int
    results: tuple[JudgmentResult, ...]
    missing_required: tuple[str, ...]
    missing_optional: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedJudgmentBundle:
    bundle: JudgmentBundle

    def result(self, question_id: str) -> JudgmentResult:
        for result in self.bundle.results:
            if result.question_id == question_id:
                return result
        raise KeyError(question_id)


class BundleValidationStatus(str, Enum):
    VALID = "VALID"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"
    STALE = "STALE"


class BundleReason(str, Enum):
    DUPLICATE_RESULT = "DUPLICATE_RESULT"
    UNKNOWN_QUESTION = "UNKNOWN_QUESTION"
    QUESTION_ID_MISMATCH = "QUESTION_ID_MISMATCH"
    SNAPSHOT_MISMATCH = "SNAPSHOT_MISMATCH"
    OBSERVATION_EPOCH_MISMATCH = "OBSERVATION_EPOCH_MISMATCH"
    MISSING_REQUIRED = "MISSING_REQUIRED"
    OPTIONAL_RESULT_MISSING = "OPTIONAL_RESULT_MISSING"
    REQUIRED_NOT_ANSWERED = "REQUIRED_NOT_ANSWERED"
    ABSTENTION_NOT_ALLOWED = "ABSTENTION_NOT_ALLOWED"
    OUTPUT_KIND_MISMATCH = "OUTPUT_KIND_MISMATCH"
    VALUE_MISSING = "VALUE_MISSING"
    NUMERIC_RANGE_INVALID = "NUMERIC_RANGE_INVALID"
    CALIBRATION_INSUFFICIENT = "CALIBRATION_INSUFFICIENT"
    RESULT_STALE = "RESULT_STALE"
    SNAPSHOT_STALE = "SNAPSHOT_STALE"


@dataclass(frozen=True)
class BundleValidation:
    status: BundleValidationStatus
    reasons: tuple[BundleReason, ...]
    validated: ValidatedJudgmentBundle | None


class PolicyStatus(str, Enum):
    SELECTED = "SELECTED"
    OBSERVE_MORE = "OBSERVE_MORE"
    WAIT = "WAIT"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class PolicyDecision:
    status: PolicyStatus
    selected_action: SemanticAction | None
    reason_codes: tuple[str, ...]
    evaluated_snapshot_id: str
    observation_epoch: int


class FreshValidationReason(str, Enum):
    NOT_SELECTED = "NOT_SELECTED"
    OBSERVATION_EPOCH_CHANGED = "OBSERVATION_EPOCH_CHANGED"
    FRESH_SNAPSHOT_STALE = "FRESH_SNAPSHOT_STALE"
    SELECTED_CANDIDATE_DISAPPEARED = "SELECTED_CANDIDATE_DISAPPEARED"
    REQUIRED_PRECONDITION_NO_LONGER_HOLDS = "REQUIRED_PRECONDITION_NO_LONGER_HOLDS"
    HARD_CONSTRAINT_CHANGED_INCOMPATIBLY = "HARD_CONSTRAINT_CHANGED_INCOMPATIBLY"
    ACTION_UNAVAILABLE = "ACTION_UNAVAILABLE"


@dataclass(frozen=True)
class ValidatedDecision:
    action: SemanticAction
    validation_snapshot_id: str
    validation_observation_epoch: int


@dataclass(frozen=True)
class FreshValidation:
    valid: bool
    reasons: tuple[FreshValidationReason, ...]
    decision: ValidatedDecision | None


@dataclass(frozen=True)
class PhysicalStep:
    operation: str
    semantic_target: str


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    semantic_action: SemanticAction
    compiled_from_snapshot: str
    observation_epoch: int
    steps: tuple[PhysicalStep, ...]


@dataclass(frozen=True)
class ExecutionEvidence:
    delivered: bool
    command_accepted: bool
    progressing: bool
    final_effect: bool


class OutcomeStage(str, Enum):
    NONE = "NONE"
    DELIVERED = "DELIVERED"
    COMMAND_ACCEPTED = "COMMAND_ACCEPTED"
    PROGRESSING = "PROGRESSING"
    FINAL_EFFECT = "FINAL_EFFECT"


@dataclass(frozen=True)
class OutcomeVerification:
    success: bool
    highest_stage: OutcomeStage
