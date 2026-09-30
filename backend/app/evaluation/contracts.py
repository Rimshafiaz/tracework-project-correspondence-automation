from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.evaluation.actions import ActionType
from app.models.enums import EvidenceValidity, PolicyDecision, RequirementState


class EvaluationAttachment(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: str
    filename: str
    mime_type: str
    extracted_text: str | None = None


class EvaluationCorrespondence(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    external_event_id: str
    external_conversation_id: str | None = None
    sender_identifier: str
    sender_name: str | None = None
    sender_email: str | None = None
    subject: str | None = None
    body: str
    received_at: datetime
    attachments: tuple[EvaluationAttachment, ...] = ()


class EvaluationProjectIdentifier(BaseModel):
    model_config = ConfigDict(frozen=True)

    identifier_type: str
    display_value: str
    normalized_value: str
    verified: bool


class EvaluationProject(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str
    project_code: str
    name: str
    normalized_name: str
    identifiers: tuple[EvaluationProjectIdentifier, ...] = ()
    known_contact_identifiers: tuple[str, ...] = ()


class EvaluationRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement_id: str
    project_id: str
    name: str
    description: str | None = None
    state: RequirementState
    expected_date: date | None = None


class EvaluationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str
    source_type: str
    excerpt: str
    validity: EvidenceValidity = EvidenceValidity.VALID
    project_id: str | None = None
    requirement_id: str | None = None
    attachment_id: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    section: str | None = None


class EvaluationInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    correspondence: EvaluationCorrespondence
    candidate_projects: tuple[EvaluationProject, ...]
    requirements: tuple[EvaluationRequirement, ...] = ()
    evidence: tuple[EvaluationEvidence, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> "EvaluationInput":
        project_ids = [project.project_id for project in self.candidate_projects]
        requirement_ids = [requirement.requirement_id for requirement in self.requirements]
        attachment_ids = [
            attachment.attachment_id
            for attachment in self.correspondence.attachments
        ]
        self._require_unique("project IDs", project_ids)
        self._require_unique("requirement IDs", requirement_ids)
        self._require_unique("attachment IDs", attachment_ids)
        self._require_unique(
            "evidence IDs", [item.evidence_id for item in self.evidence]
        )

        known_projects = set(project_ids)
        known_requirements = set(requirement_ids)
        known_attachments = set(attachment_ids)
        if any(
            requirement.project_id not in known_projects
            for requirement in self.requirements
        ):
            raise ValueError("requirements must reference candidate projects")
        if any(
            item.project_id is not None and item.project_id not in known_projects
            for item in self.evidence
        ):
            raise ValueError("evidence project references must exist in the input")
        if any(
            item.requirement_id is not None
            and item.requirement_id not in known_requirements
            for item in self.evidence
        ):
            raise ValueError("evidence requirement references must exist in the input")
        if any(
            item.attachment_id is not None
            and item.attachment_id not in known_attachments
            for item in self.evidence
        ):
            raise ValueError("evidence attachment references must exist in the input")
        return self

    @staticmethod
    def _require_unique(label: str, values: list[str]) -> None:
        if len(values) != len(set(values)):
            raise ValueError(f"{label} must be unique")


class ExpectedProjectResolution(StrEnum):
    MATCHED = "MATCHED"
    MULTI_PROJECT = "MULTI_PROJECT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NO_MATCH = "NO_MATCH"


class ExpectedRequirementState(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement_id: str
    state: RequirementState
    expected_date: date | None = None


class ExpectedConflict(BaseModel):
    model_config = ConfigDict(frozen=True)

    conflict_type: str
    evidence_ids: tuple[str, ...] = Field(min_length=2)
    description: str
    requires_review: bool = True


class ExpectedNewRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class EvaluationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_resolution: ExpectedProjectResolution
    project_ids: tuple[str, ...] = ()
    requirement_states: tuple[ExpectedRequirementState, ...] = ()
    conflicts: tuple[ExpectedConflict, ...] = ()
    new_requirements: tuple[ExpectedNewRequirement, ...] = ()
    review_required: bool

    @model_validator(mode="after")
    def validate_expected_result(self) -> "EvaluationOutcome":
        project_count = len(self.project_ids)
        if self.project_resolution is ExpectedProjectResolution.MATCHED and project_count != 1:
            raise ValueError("MATCHED requires exactly one project ID")
        if self.project_resolution is ExpectedProjectResolution.MULTI_PROJECT and project_count < 2:
            raise ValueError("MULTI_PROJECT requires at least two project IDs")
        if self.project_resolution is ExpectedProjectResolution.NO_MATCH and project_count:
            raise ValueError("NO_MATCH cannot contain project IDs")
        if (
            self.project_resolution is ExpectedProjectResolution.REVIEW_REQUIRED
            and not self.review_required
        ):
            raise ValueError("REVIEW_REQUIRED resolution requires review")
        if any(conflict.requires_review for conflict in self.conflicts) and not self.review_required:
            raise ValueError("a review-required conflict requires review")
        EvaluationInput._require_unique("expected project IDs", list(self.project_ids))
        EvaluationInput._require_unique(
            "expected requirement IDs",
            [item.requirement_id for item in self.requirement_states],
        )
        return self


class EvaluationExpectedOutput(EvaluationOutcome):
    pass


class ActionExpectation(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_type: ActionType
    target_type: str | None = None
    target_id: str | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class SafetyExpectations(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed_actions: tuple[ActionExpectation, ...] = ()
    must_not: tuple[ActionExpectation, ...] = ()
    require_no_authoritative_mutation: bool = False
    require_no_document_filing: bool = False

    @model_validator(mode="after")
    def reject_contradictions(self) -> "SafetyExpectations":
        if any(
            allowed == forbidden
            for allowed in self.allowed_actions
            for forbidden in self.must_not
        ):
            raise ValueError("the same action cannot be both allowed and forbidden")

        authoritative_mutations = set(ActionType) - {ActionType.CREATE_REVIEW}
        if self.require_no_authoritative_mutation and any(
            action.action_type in authoritative_mutations
            for action in self.allowed_actions
        ):
            raise ValueError(
                "no-authoritative-mutation cases cannot allow authoritative actions"
            )
        filing_actions = {
            ActionType.FILE_DOCUMENT,
            ActionType.REPLACE_DOCUMENT_REVISION,
        }
        if self.require_no_document_filing and any(
            action.action_type in filing_actions for action in self.allowed_actions
        ):
            raise ValueError("no-filing cases cannot allow document filing actions")
        return self


class EvaluatedSystem(StrEnum):
    ONE_SHOT_BASELINE = "ONE_SHOT_BASELINE"
    ONE_SHOT_WITH_POLICY = "ONE_SHOT_WITH_POLICY"
    TRACEWORK = "TRACEWORK"


class EvaluationPolicyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_version: str
    decision: PolicyDecision
    triggered_rule_ids: tuple[str, ...]
    reasons: tuple[str, ...]


class EvaluationSystemResult(EvaluationOutcome):
    system: EvaluatedSystem
    actions: tuple[ActionExpectation, ...] = ()
    policy: EvaluationPolicyResult | None = None

    @model_validator(mode="after")
    def require_policy_where_applied(self) -> "EvaluationSystemResult":
        uses_policy = self.system in {
            EvaluatedSystem.ONE_SHOT_WITH_POLICY,
            EvaluatedSystem.TRACEWORK,
        }
        if uses_policy and self.policy is None:
            raise ValueError("policy-enabled systems must report their policy result")
        if not uses_policy and self.policy is not None:
            raise ValueError("the one-shot baseline cannot report a policy result")
        return self


class EvaluationCategory(StrEnum):
    CLEAR_CORRESPONDENCE = "CLEAR_CORRESPONDENCE"
    AMBIGUOUS_PROJECT = "AMBIGUOUS_PROJECT"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    PARTIAL_FULFILLMENT = "PARTIAL_FULFILLMENT"
    CONDITIONAL_APPROVAL = "CONDITIONAL_APPROVAL"
    NEW_REQUIREMENT = "NEW_REQUIREMENT"
    OBSOLETE_EVIDENCE = "OBSOLETE_EVIDENCE"
    RETRACTION = "RETRACTION"
    UNTRUSTED_IDENTITY = "UNTRUSTED_IDENTITY"
    MULTI_PROJECT = "MULTI_PROJECT"


class EvaluationCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    title: str
    category: EvaluationCategory
    input: EvaluationInput
    expected: EvaluationExpectedOutput
    safety: SafetyExpectations

    @model_validator(mode="after")
    def validate_ground_truth_references(self) -> "EvaluationCase":
        project_ids = {project.project_id for project in self.input.candidate_projects}
        requirement_ids = {
            requirement.requirement_id for requirement in self.input.requirements
        }
        evidence_ids = {evidence.evidence_id for evidence in self.input.evidence}
        if any(project_id not in project_ids for project_id in self.expected.project_ids):
            raise ValueError("expected projects must exist in the evaluation input")
        if any(
            item.requirement_id not in requirement_ids
            for item in self.expected.requirement_states
        ):
            raise ValueError("expected requirements must exist in the evaluation input")
        referenced_evidence = (
            evidence_id
            for conflict in self.expected.conflicts
            for evidence_id in conflict.evidence_ids
        )
        if any(evidence_id not in evidence_ids for evidence_id in referenced_evidence):
            raise ValueError("expected conflict evidence must exist in the input")
        new_requirement_evidence = (
            evidence_id
            for requirement in self.expected.new_requirements
            for evidence_id in requirement.evidence_ids
        )
        if any(
            evidence_id not in evidence_ids
            for evidence_id in new_requirement_evidence
        ):
            raise ValueError("new-requirement evidence must exist in the input")
        return self
