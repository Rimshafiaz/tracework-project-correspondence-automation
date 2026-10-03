from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.models.enums import AttachmentProcessingState, EvidenceValidity, RequirementState
from app.services.requirement_reconciliation_context import AuthoritativeProjectLinkNotFound, RequirementContextLimitExceeded, RequirementReconciliationContextService


class FakeRepository:
    def __init__(self, *, item=None, items=()) -> None:
        self.item = item
        self.items = items

    def get(self, _item_id):
        return self.item

    def list_for_project(self, _project_id):
        return self.items

    def list_for_correspondence_event(self, _event_id):
        return self.items

    def list_valid_evidence_for_requirements(self, **_kwargs):
        return self.items


def _service(
    *,
    requirements=(),
    attachments=(),
    evidence=(),
    max_requirements=10,
    max_attachments=10,
    max_source_characters=10_000,
):
    project_id = uuid4()
    event_id = uuid4()
    link = SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        correspondence_event_id=event_id,
    )
    correspondence = SimpleNamespace(
        id=event_id,
        source="fixture",
        external_conversation_id="thread-1",
        sender_identifier="sender@example.test",
        sender_name="Example Sender",
        sender_email="sender@example.test",
        subject="Requirement update",
        body="The report is complete.",
        received_at=datetime.now(UTC),
    )
    service = RequirementReconciliationContextService(
        project_link_repository=FakeRepository(item=link),
        correspondence_repository=FakeRepository(item=correspondence),
        requirement_repository=FakeRepository(items=requirements),
        attachment_repository=FakeRepository(items=attachments),
        lineage_repository=FakeRepository(items=evidence),
        max_requirements=max_requirements,
        max_attachments=max_attachments,
        max_source_characters=max_source_characters,
    )
    return service, link


def _requirement(*, project_id: UUID | None = None):
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        name="Provide report",
        description="A final report is required.",
        state=RequirementState.OPEN,
        expected_date=None,
    )


def test_builds_context_for_the_one_authoritative_project() -> None:
    requirement = _requirement()
    attachment = SimpleNamespace(
        id=uuid4(),
        filename="report.pdf",
        mime_type="application/pdf",
        processing_state=AttachmentProcessingState.EXTRACTED,
        extracted_text="Final report content",
        extraction_metadata={"schema_version": 1},
        content_hash="a" * 64,
    )
    service, link = _service(requirements=(requirement,), attachments=(attachment,))

    context = service.build(link.id)

    assert context.project_id == link.project_id
    assert context.authoritative_project_link_id == link.id
    assert context.requirements[0].requirement_id == requirement.id
    assert context.attachments[0].attachment_id == attachment.id


@pytest.mark.parametrize(
    "arguments,expected_kind",
    [
        ({"requirements": (_requirement(),), "max_requirements": 0}, None),
        ({"requirements": (_requirement(), _requirement()), "max_requirements": 1}, "REQUIREMENT_COUNT"),
        ({"attachments": (object(), object()), "max_attachments": 1}, "ATTACHMENT_COUNT"),
        ({"max_source_characters": 5}, "SOURCE_CHARACTER_COUNT"),
    ],
)
def test_rejects_invalid_or_exceeded_context_bounds(arguments, expected_kind) -> None:
    if expected_kind is None:
        with pytest.raises(ValueError, match="must be positive"):
            _service(**arguments)
        return
    service, link = _service(**arguments)
    with pytest.raises(RequirementContextLimitExceeded) as exc_info:
        service.build(link.id)
    assert exc_info.value.outcome.limit_kind.value == expected_kind


def test_missing_authoritative_link_stops_context_assembly() -> None:
    repository = FakeRepository(item=None)
    service = RequirementReconciliationContextService(
        project_link_repository=repository,
        correspondence_repository=repository,
        requirement_repository=repository,
        attachment_repository=repository,
        lineage_repository=repository,
        max_requirements=10,
        max_attachments=10,
        max_source_characters=10_000,
    )

    with pytest.raises(AuthoritativeProjectLinkNotFound):
        service.build(uuid4())
