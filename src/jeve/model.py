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
        return cls(f"RETREAT:{destination_id}", ActionKind.RETREAT, destination_id=destination_id)

    @property
    def resource_claims(self) -> tuple[str, ...]:
        if self.kind in {ActionKind.TAKE_ROUTE, ActionKind.RETREAT}:
            return ("navigation",)
        return ()


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
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class CalibrationProvenance:
    authority: str
    basis: str
    provider_id: str
    model_id: str
    schema_version: str
    evaluation_population: str
    metric_name: str
    metric_value: float

    def __post_init__(self) -> None:
        for value in (
            self.authority,
            self.basis,
            self.provider_id,
            self.model_id,
            self.schema_version,
            self.evaluation_population,
            self.metric_name,
        ):
            if not value.strip():
                raise ValueError("calibration provenance fields must be non-empty")
        if not 0.0 <= self.metric_value <= 1.0:
            raise ValueError("metric_value must be within [0, 1]")


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
    freshness_dependencies: tuple[str, ...] = ()
    correlation_key: str | None = None
    schema_version: str = "1"


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
    result_id: str = ""
    provider_id: str = "fake-provider"
    model_id: str = "fake-model"
    schema_version: str = "1"
    equivalence_key: str = ""
    dependency_key: str = ""
    calibration_provenance: CalibrationProvenance | None = None


@dataclass(frozen=True)
class JudgmentBundle:
    plan_id: str
    snapshot_id: str
    observation_epoch: int
    results: tuple[JudgmentResult, ...]
    missing_required: tuple[str, ...]
    missing_optional: tuple[str, ...]


_POLICY_BUNDLE_SEAL = object()


class PolicyUsableJudgmentBundle:
    __slots__ = ("_bundle", "_equivalence_keys", "_valid_until")

    def __init__(
        self,
        bundle: JudgmentBundle,
        equivalence_keys: tuple[tuple[str, str], ...],
        valid_until: int,
        seal: object,
    ) -> None:
        if seal is not _POLICY_BUNDLE_SEAL:
            raise TypeError("PolicyUsableJudgmentBundle is issued by JudgmentBundleValidator")
        self._bundle = bundle
        self._equivalence_keys = equivalence_keys
        self._valid_until = valid_until

    @classmethod
    def _issue(
        cls,
        bundle: JudgmentBundle,
        equivalence_keys: tuple[tuple[str, str], ...],
        valid_until: int,
    ) -> "PolicyUsableJudgmentBundle":
        return cls(bundle, equivalence_keys, valid_until, _POLICY_BUNDLE_SEAL)

    @property
    def bundle(self) -> JudgmentBundle:
        return self._bundle

    @property
    def equivalence_keys(self) -> tuple[tuple[str, str], ...]:
        return self._equivalence_keys

    @property
    def valid_until(self) -> int:
        return self._valid_until

    def result(self, question_id: str) -> JudgmentResult:
        for result in self._bundle.results:
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
    SNAPSHOT_MISMATCH = "SNAPSHOT_MISMATCH"
    OBSERVATION_EPOCH_MISMATCH = "OBSERVATION_EPOCH_MISMATCH"
    MISSING_REQUIRED = "MISSING_REQUIRED"
    OPTIONAL_RESULT_MISSING = "OPTIONAL_RESULT_MISSING"
    ABSTENTION_NOT_ALLOWED = "ABSTENTION_NOT_ALLOWED"
    OUTPUT_KIND_MISMATCH = "OUTPUT_KIND_MISMATCH"
    VALUE_MISSING = "VALUE_MISSING"
    NUMERIC_RANGE_INVALID = "NUMERIC_RANGE_INVALID"
    CALIBRATION_INSUFFICIENT = "CALIBRATION_INSUFFICIENT"
    CALIBRATION_PROVENANCE_MISSING = "CALIBRATION_PROVENANCE_MISSING"
    CALIBRATION_PROVENANCE_MISMATCH = "CALIBRATION_PROVENANCE_MISMATCH"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    RESULT_STALE = "RESULT_STALE"
    SNAPSHOT_STALE = "SNAPSHOT_STALE"
    EQUIVALENCE_KEY_MISMATCH = "EQUIVALENCE_KEY_MISMATCH"


@dataclass(frozen=True)
class BundleValidation:
    status: BundleValidationStatus
    reasons: tuple[BundleReason, ...]
    validated: PolicyUsableJudgmentBundle | None


class PolicyStatus(str, Enum):
    SELECTED = "SELECTED"
    OBSERVE_MORE = "OBSERVE_MORE"
    WAIT = "WAIT"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class JudgmentBinding:
    question_id: str
    result_id: str
    value_kind: ValueKind
    value: float
    equivalence_key: str
    provider_id: str
    model_id: str
    schema_version: str
    dependency_key: str
    valid_until: int


@dataclass(frozen=True)
class PolicyDecision:
    status: PolicyStatus
    selected_action: SemanticAction | None
    reason_codes: tuple[str, ...]
    evaluated_snapshot_id: str
    observation_epoch: int
    created_at: int
    expires_at: int
    semantic_input_key: str
    policy_config_key: str
    judgment_bindings: tuple[JudgmentBinding, ...]


class FreshValidationReason(str, Enum):
    NOT_SELECTED = "NOT_SELECTED"
    OBSERVATION_EPOCH_CHANGED = "OBSERVATION_EPOCH_CHANGED"
    FRESH_SNAPSHOT_STALE = "FRESH_SNAPSHOT_STALE"
    DECISION_EXPIRED = "DECISION_EXPIRED"
    SEMANTIC_INPUTS_CHANGED = "SEMANTIC_INPUTS_CHANGED"
    POLICY_CONFIG_CHANGED = "POLICY_CONFIG_CHANGED"
    JUDGMENT_EVIDENCE_CHANGED = "JUDGMENT_EVIDENCE_CHANGED"
    JUDGMENT_EVIDENCE_EXPIRED = "JUDGMENT_EVIDENCE_EXPIRED"
    SELECTED_CANDIDATE_DISAPPEARED = "SELECTED_CANDIDATE_DISAPPEARED"
    REQUIRED_PRECONDITION_NO_LONGER_HOLDS = "REQUIRED_PRECONDITION_NO_LONGER_HOLDS"
    HARD_CONSTRAINT_CHANGED_INCOMPATIBLY = "HARD_CONSTRAINT_CHANGED_INCOMPATIBLY"
    ACTION_UNAVAILABLE = "ACTION_UNAVAILABLE"


@dataclass(frozen=True)
class ValidatedDecision:
    action: SemanticAction
    validation_snapshot_id: str
    validation_observation_epoch: int
    resource_claims: tuple[str, ...]


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
    resource_claims: tuple[str, ...]


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


class IntentAdmissionStatus(str, Enum):
    ADMITTED = "ADMITTED"
    DUPLICATE_PENDING_INTENT = "DUPLICATE_PENDING_INTENT"
    RESOURCE_BUSY = "RESOURCE_BUSY"


@dataclass(frozen=True)
class PendingIntent:
    intent_id: str
    action: SemanticAction
    resource_claims: tuple[str, ...]


@dataclass(frozen=True)
class IntentAdmission:
    status: IntentAdmissionStatus
    pending: PendingIntent | None


@dataclass(frozen=True)
class DecisionTrace:
    trace_id: str
    snapshot: StateSnapshot
    reduction: ReductionResult
    judgment_plan: JudgmentPlan
    judgment_results: tuple[JudgmentResult, ...]
    bundle_status: BundleValidationStatus
    judgment_freshness_max_age: int
    calibration_policy_key: str
    policy_config_key: str
    policy_decision: PolicyDecision
    fresh_validation: FreshValidation | None = None
    execution_plan: ExecutionPlan | None = None
    outcome: OutcomeVerification | None = None
