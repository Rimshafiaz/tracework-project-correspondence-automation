from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.evaluation.contracts import EvaluationAttachment, EvaluationCorrespondence, EvaluationEvidence, EvaluationInput, EvaluationProject, EvaluationProjectIdentifier, EvaluationRequirement
from app.models.enums import RequirementState


def build_input() -> EvaluationInput:
    project = EvaluationProject(
        project_id="project-alpha",
        project_code="ALPHA",
        name="Example Project",
        normalized_name="example project",
        identifiers=(
            EvaluationProjectIdentifier(
                identifier_type="external_reference",
                display_value="External 42",
                normalized_value="external 42",
                verified=True,
            ),
        ),
        known_contact_identifiers=("contact@example.com",),
    )
    requirement = EvaluationRequirement(
        requirement_id="requirement-one",
        project_id=project.project_id,
        name="Approval",
        state=RequirementState.OPEN,
    )
    attachment = EvaluationAttachment(
        attachment_id="attachment-one",
        filename="approval.txt",
        mime_type="text/plain",
        extracted_text="Approved with one item outstanding.",
    )
    return EvaluationInput(
        correspondence=EvaluationCorrespondence(
            source="fixture",
            external_event_id="event-one",
            sender_identifier="contact@example.com",
            body="Please review the attached update.",
            received_at=datetime(2026, 10, 1, tzinfo=UTC),
            attachments=(attachment,),
        ),
        candidate_projects=(project,),
        requirements=(requirement,),
        evidence=(
            EvaluationEvidence(
                evidence_id="evidence-one",
                source_type="attachment_text",
                excerpt="Approved with one item outstanding.",
                project_id=project.project_id,
                requirement_id=requirement.requirement_id,
                attachment_id=attachment.attachment_id,
            ),
        ),
    )


def test_input_exposes_the_same_neutral_context_to_every_system() -> None:
    evaluation_input = build_input()

    assert evaluation_input.correspondence.source == "fixture"
    assert evaluation_input.candidate_projects[0].identifiers[0].verified is True
    assert evaluation_input.requirements[0].state is RequirementState.OPEN
    assert evaluation_input.evidence[0].attachment_id == "attachment-one"
    assert "expected" not in EvaluationInput.model_fields


def test_input_rejects_duplicate_stable_ids() -> None:
    evaluation_input = build_input()

    with pytest.raises(ValidationError, match="project IDs must be unique"):
        EvaluationInput(
            correspondence=evaluation_input.correspondence,
            candidate_projects=(
                evaluation_input.candidate_projects[0],
                evaluation_input.candidate_projects[0],
            ),
        )


def test_input_rejects_dangling_requirement_reference() -> None:
    evaluation_input = build_input()
    invalid_requirement = evaluation_input.requirements[0].model_copy(
        update={"project_id": "missing-project"}
    )

    with pytest.raises(
        ValidationError,
        match="requirements must reference candidate projects",
    ):
        EvaluationInput(
            correspondence=evaluation_input.correspondence,
            candidate_projects=evaluation_input.candidate_projects,
            requirements=(invalid_requirement,),
        )


def test_input_rejects_dangling_evidence_reference() -> None:
    evaluation_input = build_input()
    invalid_evidence = evaluation_input.evidence[0].model_copy(
        update={"attachment_id": "missing-attachment"}
    )

    with pytest.raises(
        ValidationError,
        match="evidence attachment references must exist",
    ):
        EvaluationInput(
            correspondence=evaluation_input.correspondence,
            candidate_projects=evaluation_input.candidate_projects,
            requirements=evaluation_input.requirements,
            evidence=(invalid_evidence,),
        )
