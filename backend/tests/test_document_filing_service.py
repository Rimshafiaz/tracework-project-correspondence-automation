import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.ai.schemas import (
    CandidateSignalReference,
    EvidenceConflict,
    ProjectResolution,
    ResolutionEvidence,
    ResolutionStatus,
    ResolverSourceField,
    SourceTextEvidence,
)
from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType
from app.contracts.document_filing import (
    DriveFileRecord,
    DocumentFilingOutcomeStatus,
    DocumentFilingSkipReason,
)
from app.models.enums import DocumentFilingStatus, PolicyDecision, ReviewStatus, TransitionStatus
from app.services.document_filing import (
    AttachmentContentUnavailable,
    DOCUMENT_FILED_AUDIT_EVENT,
    DocumentFilingService,
)
from app.adapters.drive.client import DriveProviderError


def _source(attachment_id):
    return SourceTextEvidence(
        correspondence_event_id=EVENT_ID,
        source_field=ResolverSourceField.ATTACHMENT_TEXT,
        attachment_id=attachment_id,
        excerpt="Project reference",
    )


EVENT_ID = uuid4()


def _fixture(*, decision=PolicyDecision.ALLOW_AUTO_ACTION, project_count=1, resolution=None):
    event = SimpleNamespace(id=EVENT_ID, source="gmail")
    content = b"document bytes"
    attachment = SimpleNamespace(
        id=uuid4(),
        correspondence_event_id=EVENT_ID,
        filename="report.pdf",
        mime_type="application/pdf",
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    project_ids = tuple(uuid4() for _ in range(project_count))
    if resolution is None:
        resolution = ProjectResolution(
            status=(ResolutionStatus.MATCHED if project_count == 1 else ResolutionStatus.MULTI_PROJECT),
            project_ids=project_ids,
            evidence=tuple(
                ResolutionEvidence(
                    project_id=project_id,
                    source_evidence=(_source(attachment.id),),
                    interpretation="Attachment identifies the project.",
                )
                for project_id in project_ids
            ),
        )
    proposal = SimpleNamespace(
        id=uuid4(),
        correspondence_event_id=EVENT_ID,
        correspondence_event=event,
        structured_output=resolution.model_dump(mode="json"),
    )
    evaluation = SimpleNamespace(
        id=uuid4(),
        ai_proposal_id=proposal.id,
        decision=decision,
    )
    session = MagicMock()
    drive = MagicMock()
    attachments = MagicMock()
    attachments.list_for_correspondence_event.return_value = (attachment,)
    documents = MagicMock()
    projects = MagicMock()
    projects.get.side_effect = lambda project_id: SimpleNamespace(
        id=project_id, project_code="TW-001", name="Project"
    )
    links = MagicMock()
    links.list_approved_project_ids_for_event.return_value = project_ids
    reviews = MagicMock()
    lineage = MagicMock()
    lineage.get_proposal.return_value = proposal
    lineage.get_policy_evaluation_by_id.return_value = evaluation
    lineage.list_policy_evidence.return_value = ()
    lineage.get_audit_event_for_transition.return_value = None
    revisions = MagicMock()
    service = DocumentFilingService(
        session=session,
        drive_client=drive,
        root_folder_name="Tracework",
        default_category="Documents",
        content_loader=lambda _event, _attachment: content,
        attachment_repository=attachments,
        document_repository=documents,
        project_repository=projects,
        project_link_repository=links,
        review_repository=reviews,
        lineage_repository=lineage,
        revision_service=revisions,
    )
    return SimpleNamespace(**locals())


def _configure_success(deps):
    document = SimpleNamespace(
        id=uuid4(),
        source_attachment_id=deps.attachment.id,
        filename=deps.attachment.filename,
        category="Documents",
        content_hash=deps.attachment.content_hash,
        filing_status=DocumentFilingStatus.PENDING,
        drive_file_id=None,
    )
    transition = SimpleNamespace(id=uuid4(), status=TransitionStatus.PREVIEWED)
    deps.documents.get_by_project_attachment.side_effect = [None, None]
    deps.documents.create_pending.return_value = document
    deps.documents.get_for_update.return_value = document
    deps.lineage.get_state_transition_for_update.side_effect = [None, transition]
    deps.lineage.create_transition.return_value = transition
    deps.drive.ensure_folder.side_effect = ["root", "project", "category"]
    deps.drive.find_file.return_value = None
    deps.drive.upload_file.return_value = DriveFileRecord(
        file_id="drive-file",
        name=deps.attachment.filename,
        parent_folder_id="category",
    )

    def mark_filed(item, **values):
        item.filing_status = DocumentFilingStatus.FILED
        item.drive_file_id = values["drive_file_id"]
        item.drive_parent_folder_id = values["drive_parent_folder_id"]
        item.filed_at = values["filed_at"]
        return item

    deps.documents.mark_filed.side_effect = mark_filed
    return document, transition


def test_policy_approved_attachment_files_and_persists_hash_id_and_audit():
    deps = _fixture()
    document, transition = _configure_success(deps)

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id,
        policy_evaluation_id=deps.evaluation.id,
    )

    assert result.outcomes[0].status is DocumentFilingOutcomeStatus.FILED
    deps.documents.create_pending.assert_called_once_with(
        project_id=deps.project_ids[0],
        source_attachment_id=deps.attachment.id,
        filename="report.pdf",
        category="Documents",
        content_hash=deps.attachment.content_hash,
    )
    deps.documents.mark_filed.assert_called_once()
    deps.lineage.mark_transition_applied.assert_called_once_with(
        transition, applied_at=document.filed_at
    )
    assert deps.lineage.create_audit_event.call_args.kwargs["event_type"] == DOCUMENT_FILED_AUDIT_EVENT
    assert deps.lineage.create_audit_event.call_args.kwargs["details"]["drive_file_id"] == "drive-file"
    deps.revisions.evaluate_filed_document.assert_called_once_with(
        document_id=document.id,
        correspondence_event_id=deps.event.id,
        ai_proposal_id=deps.proposal.id,
        policy_evaluation_id=deps.evaluation.id,
    )


def test_unresolved_or_rejected_project_never_calls_drive():
    deps = _fixture(decision=PolicyDecision.REJECT_PROPOSAL)
    deps.links.list_approved_project_ids_for_event.return_value = ()

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].skip_reason is DocumentFilingSkipReason.PROJECT_NOT_AUTHORIZED
    deps.drive.ensure_folder.assert_not_called()


def test_pending_project_review_never_calls_drive():
    deps = _fixture(decision=PolicyDecision.REVIEW_REQUIRED)
    transition = SimpleNamespace(id=uuid4())
    deps.reviews.get_project_resolution_transition.return_value = transition
    deps.reviews.get_by_state_transition.return_value = SimpleNamespace(status=ReviewStatus.PENDING)

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].skip_reason is DocumentFilingSkipReason.PROJECT_REVIEW_PENDING
    deps.drive.ensure_folder.assert_not_called()


def test_resolved_human_review_may_file_to_single_authoritative_project():
    deps = _fixture(decision=PolicyDecision.REVIEW_REQUIRED)
    transition = SimpleNamespace(id=uuid4())
    deps.reviews.get_project_resolution_transition.return_value = transition
    deps.reviews.get_by_state_transition.return_value = SimpleNamespace(status=ReviewStatus.CORRECTED)
    _configure_success(deps)

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].status is DocumentFilingOutcomeStatus.FILED


def test_multi_project_attachment_without_unique_scope_is_not_duplicated():
    deps = _fixture(project_count=2)

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].skip_reason is DocumentFilingSkipReason.MULTI_PROJECT_ATTACHMENT_AMBIGUOUS
    deps.drive.ensure_folder.assert_not_called()


def test_multi_project_attachment_with_one_scoped_project_files_once():
    deps = _fixture(project_count=2)
    deps.proposal.structured_output = ProjectResolution(
        status=ResolutionStatus.MULTI_PROJECT,
        project_ids=deps.project_ids,
        evidence=(
            ResolutionEvidence(
                project_id=deps.project_ids[0],
                source_evidence=(_source(deps.attachment.id),),
                interpretation="Attachment belongs to the first project.",
            ),
            ResolutionEvidence(
                project_id=deps.project_ids[1],
                source_evidence=(
                    SourceTextEvidence(
                        correspondence_event_id=EVENT_ID,
                        source_field=ResolverSourceField.BODY,
                        excerpt="Second project",
                    ),
                ),
                interpretation="Message also concerns the second project.",
            ),
        ),
    ).model_dump(mode="json")
    _configure_success(deps)

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].project_id == deps.project_ids[0]
    deps.drive.upload_file.assert_called_once()


def test_attachment_scoped_conflict_blocks_multi_project_filing():
    attachment_id = uuid4()
    project_a, project_b = uuid4(), uuid4()
    resolution = ProjectResolution(
        status=ResolutionStatus.MULTI_PROJECT,
        project_ids=(project_a, project_b),
        evidence=(
            ResolutionEvidence(
                project_id=project_a,
                source_evidence=(_source(attachment_id),),
                interpretation="Project A",
            ),
            ResolutionEvidence(
                project_id=project_b,
                source_evidence=(_source(attachment_id),),
                interpretation="Project B",
            ),
        ),
        conflicts=(
            EvidenceConflict(
                project_ids=(project_a, project_b),
                source_evidence=(_source(attachment_id), _source(attachment_id)),
                description="Attachment identity conflicts.",
            ),
        ),
    )
    project_id, reason = DocumentFilingService._attachment_project(
        attachment_id=attachment_id,
        authoritative_project_ids=(project_a, project_b),
        resolution=resolution,
    )

    assert project_id is None
    assert reason is DocumentFilingSkipReason.ATTACHMENT_PROJECT_CONFLICT


@pytest.mark.parametrize("review_status", [None, ReviewStatus.APPROVED, ReviewStatus.CORRECTED])
@pytest.mark.parametrize("support_kind", ["source", "signal"])
def test_single_authoritative_project_never_bypasses_attachment_conflict(
    review_status, support_kind
):
    deps = _fixture(
        decision=(
            PolicyDecision.ALLOW_AUTO_ACTION
            if review_status is None
            else PolicyDecision.REVIEW_REQUIRED
        )
    )
    project_a = deps.project_ids[0]
    project_b = uuid4()
    source = _source(deps.attachment.id)
    signal = CandidateSignalReference(
        project_id=project_b,
        signal_type=CandidateSignalType.PROJECT_CODE,
        matched_value="TW-002",
        source=CandidateSignalSource.ATTACHMENT,
        attachment_id=deps.attachment.id,
    )
    deps.proposal.structured_output = ProjectResolution(
        status=ResolutionStatus.MATCHED,
        project_ids=(project_a,),
        evidence=(
            ResolutionEvidence(
                project_id=project_a,
                source_evidence=(SourceTextEvidence(
                    correspondence_event_id=EVENT_ID,
                    source_field=ResolverSourceField.BODY,
                    excerpt="Correspondence project",
                ),),
                interpretation="The correspondence concerns Project A.",
            ),
        ),
        conflicts=(EvidenceConflict(
            project_ids=(project_a, project_b),
            source_evidence=(source, source) if support_kind == "source" else (source,),
            signal_references=(signal,) if support_kind == "signal" else (),
            description="Attachment project differs from correspondence project.",
        ),),
    ).model_dump(mode="json")
    if review_status is not None:
        deps.reviews.get_project_resolution_transition.return_value = SimpleNamespace(id=uuid4())
        deps.reviews.get_by_state_transition.return_value = SimpleNamespace(status=review_status)

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].skip_reason is DocumentFilingSkipReason.ATTACHMENT_PROJECT_CONFLICT
    deps.drive.ensure_folder.assert_not_called()
    deps.drive.find_file.assert_not_called()
    deps.drive.upload_file.assert_not_called()
    deps.documents.create_pending.assert_not_called()
    deps.lineage.create_transition.assert_not_called()


@pytest.mark.parametrize("project_count", [1, 2])
@pytest.mark.parametrize("review_status", [None, ReviewStatus.APPROVED, ReviewStatus.CORRECTED])
def test_attachment_evidence_for_other_project_blocks_without_explicit_conflict(
    project_count, review_status
):
    deps = _fixture(
        project_count=project_count,
        decision=(
            PolicyDecision.ALLOW_AUTO_ACTION
            if review_status is None
            else PolicyDecision.REVIEW_REQUIRED
        ),
    )
    resolution = ProjectResolution.model_validate(deps.proposal.structured_output)
    deps.proposal.structured_output = resolution.model_copy(update={
        "evidence": (*resolution.evidence, ResolutionEvidence(
            project_id=uuid4(),
            source_evidence=(_source(deps.attachment.id),),
            interpretation="Attachment also identifies a different project.",
        )),
    }).model_dump(mode="json")
    if review_status is not None:
        deps.reviews.get_project_resolution_transition.return_value = SimpleNamespace(id=uuid4())
        deps.reviews.get_by_state_transition.return_value = SimpleNamespace(status=review_status)

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].skip_reason is DocumentFilingSkipReason.ATTACHMENT_PROJECT_CONFLICT
    deps.drive.ensure_folder.assert_not_called()
    deps.drive.find_file.assert_not_called()
    deps.drive.upload_file.assert_not_called()
    deps.documents.create_pending.assert_not_called()


def test_existing_filed_document_is_an_idempotent_no_op():
    deps = _fixture()
    document = SimpleNamespace(id=uuid4(), filing_status=DocumentFilingStatus.FILED)
    transition = SimpleNamespace(id=uuid4())
    deps.documents.get_by_project_attachment.return_value = document
    deps.lineage.get_state_transition.return_value = transition

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].status is DocumentFilingOutcomeStatus.ALREADY_FILED
    deps.drive.ensure_folder.assert_not_called()
    deps.drive.upload_file.assert_not_called()
    deps.revisions.evaluate_filed_document.assert_called_once_with(
        document_id=document.id,
        correspondence_event_id=deps.event.id,
        ai_proposal_id=deps.proposal.id,
        policy_evaluation_id=deps.evaluation.id,
    )


def test_provider_failure_leaves_retryable_document_without_false_success():
    deps = _fixture()
    document, transition = _configure_success(deps)
    deps.drive.ensure_folder.side_effect = DriveProviderError("unavailable")

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].status is DocumentFilingOutcomeStatus.RETRYABLE_FAILURE
    deps.documents.mark_retryable_failure.assert_called_once_with(
        document, failure_code="DRIVE_PROVIDER_UNAVAILABLE"
    )
    deps.documents.mark_filed.assert_not_called()
    deps.lineage.mark_transition_applied.assert_not_called()


def test_retry_recovers_uploaded_file_by_document_identity_without_uploading_again():
    deps = _fixture()
    _configure_success(deps)
    deps.drive.find_file.return_value = DriveFileRecord(
        file_id="already-uploaded",
        name="report.pdf",
        parent_folder_id="category",
    )

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].status is DocumentFilingOutcomeStatus.FILED
    deps.drive.upload_file.assert_not_called()


def test_concurrent_worker_reuses_completion_observed_under_document_lock():
    deps = _fixture()
    pending, transition = _configure_success(deps)
    completed = SimpleNamespace(
        id=pending.id,
        source_attachment_id=deps.attachment.id,
        filename=pending.filename,
        category=pending.category,
        content_hash=pending.content_hash,
        filing_status=DocumentFilingStatus.FILED,
        drive_file_id="other-worker-file",
    )
    deps.documents.get_for_update.return_value = completed

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].status is DocumentFilingOutcomeStatus.ALREADY_FILED
    assert result.outcomes[0].state_transition_id == transition.id
    deps.drive.ensure_folder.assert_not_called()
    deps.drive.upload_file.assert_not_called()


def test_content_hash_mismatch_never_calls_drive_or_creates_document():
    deps = _fixture()
    deps.service.content_loader = lambda _event, _attachment: b"different"

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].skip_reason is DocumentFilingSkipReason.ATTACHMENT_CONTENT_MISMATCH
    deps.documents.create_pending.assert_not_called()
    deps.drive.ensure_folder.assert_not_called()


def test_unavailable_attachment_bytes_leave_no_false_document():
    deps = _fixture()

    def unavailable(_event, _attachment):
        raise AttachmentContentUnavailable("not available")

    deps.service.content_loader = unavailable

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].skip_reason is DocumentFilingSkipReason.ATTACHMENT_CONTENT_UNAVAILABLE
    deps.documents.create_pending.assert_not_called()
    deps.drive.ensure_folder.assert_not_called()


def _configure_existing_retry(deps):
    document, transition = _configure_success(deps)
    deps.documents.get_by_project_attachment.side_effect = None
    deps.documents.get_by_project_attachment.return_value = document
    deps.lineage.get_state_transition_for_update.side_effect = None
    deps.lineage.get_state_transition_for_update.return_value = transition
    deps.lineage.get_state_transition.return_value = transition
    deps.drive.ensure_folder.side_effect = lambda **kwargs: (
        kwargs["app_properties"]["tracework_kind"]
    )

    def mark_failure(item, **kwargs):
        item.filing_status = DocumentFilingStatus.RETRYABLE_FAILURE
        item.failure_code = kwargs["failure_code"]

    def mark_transition(item, **kwargs):
        item.status = TransitionStatus.APPLIED
        item.applied_at = kwargs["applied_at"]

    deps.documents.mark_retryable_failure.side_effect = mark_failure
    deps.lineage.mark_transition_applied.side_effect = mark_transition
    return document, transition


def test_failed_document_retries_same_records_and_success_occurs_once():
    deps = _fixture()
    document, transition = _configure_existing_retry(deps)
    deps.drive.find_file.side_effect = [DriveProviderError("unavailable"), None]

    failed = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )
    assert failed.outcomes[0].status is DocumentFilingOutcomeStatus.RETRYABLE_FAILURE
    assert document.filing_status is DocumentFilingStatus.RETRYABLE_FAILURE
    assert transition.status is TransitionStatus.PREVIEWED

    succeeded = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )
    repeated = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert succeeded.outcomes[0].document_id == failed.outcomes[0].document_id == document.id
    assert succeeded.outcomes[0].state_transition_id == transition.id
    assert repeated.outcomes[0].status is DocumentFilingOutcomeStatus.ALREADY_FILED
    assert document.filing_status is DocumentFilingStatus.FILED
    assert transition.status is TransitionStatus.APPLIED
    deps.documents.create_pending.assert_not_called()
    deps.lineage.create_transition.assert_not_called()
    deps.drive.upload_file.assert_called_once()
    deps.documents.mark_filed.assert_called_once()
    deps.lineage.mark_transition_applied.assert_called_once()
    deps.lineage.create_audit_event.assert_called_once()


def test_upload_before_database_failure_is_recovered_without_duplicate_upload():
    deps = _fixture()
    document, transition = _configure_existing_retry(deps)
    uploaded = None

    def upload(**kwargs):
        nonlocal uploaded
        uploaded = DriveFileRecord(
            file_id="recovered-file", name=kwargs["name"],
            parent_folder_id=kwargs["parent_folder_id"],
        )
        assert kwargs["app_properties"]["tracework_document_id"] == str(document.id)
        return uploaded

    deps.drive.upload_file.side_effect = upload
    deps.drive.find_file.side_effect = lambda **kwargs: uploaded
    original_mark_filed = deps.documents.mark_filed.side_effect
    deps.documents.mark_filed.side_effect = RuntimeError("database finalization failed")

    with pytest.raises(RuntimeError, match="database finalization"):
        deps.service.file_for_project_resolution(
            proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
        )
    deps.session.rollback()
    assert uploaded is not None
    assert document.filing_status is DocumentFilingStatus.PENDING
    deps.documents.mark_filed.side_effect = original_mark_filed
    deps.documents.mark_filed.reset_mock()

    recovered = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )
    repeated = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert recovered.outcomes[0].document_id == document.id
    assert repeated.outcomes[0].status is DocumentFilingOutcomeStatus.ALREADY_FILED
    assert document.drive_file_id == "recovered-file"
    deps.drive.upload_file.assert_called_once()
    deps.documents.create_pending.assert_not_called()
    deps.lineage.create_transition.assert_not_called()
    deps.documents.mark_filed.assert_called_once()
    deps.lineage.mark_transition_applied.assert_called_once()
    deps.lineage.create_audit_event.assert_called_once()
    assert deps.revisions.evaluate_filed_document.call_count == 2


def test_retry_rechecks_authorization_before_touching_existing_failed_document():
    deps = _fixture()
    document, _ = _configure_existing_retry(deps)
    document.filing_status = DocumentFilingStatus.RETRYABLE_FAILURE
    deps.links.list_approved_project_ids_for_event.return_value = ()

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].skip_reason is DocumentFilingSkipReason.PROJECT_NOT_AUTHORIZED
    deps.drive.ensure_folder.assert_not_called()
    deps.documents.get_by_project_attachment.assert_not_called()


def test_retry_rechecks_attachment_safety_before_touching_failed_document():
    deps = _fixture()
    document, _ = _configure_existing_retry(deps)
    document.filing_status = DocumentFilingStatus.RETRYABLE_FAILURE
    resolution = ProjectResolution.model_validate(deps.proposal.structured_output)
    deps.proposal.structured_output = resolution.model_copy(update={
        "evidence": (*resolution.evidence, ResolutionEvidence(
            project_id=uuid4(), source_evidence=(_source(deps.attachment.id),),
            interpretation="Attachment identifies another project.",
        )),
    }).model_dump(mode="json")

    result = deps.service.file_for_project_resolution(
        proposal_id=deps.proposal.id, policy_evaluation_id=deps.evaluation.id
    )

    assert result.outcomes[0].skip_reason is DocumentFilingSkipReason.ATTACHMENT_PROJECT_CONFLICT
    deps.drive.ensure_folder.assert_not_called()
    deps.documents.get_by_project_attachment.assert_not_called()
