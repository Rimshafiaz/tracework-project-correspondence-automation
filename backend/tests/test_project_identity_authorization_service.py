from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.ai.schemas import CandidateSignalReference, ProjectResolution, ResolutionConcern, ResolutionEvidence, ResolutionStatus
from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType, ProjectCandidate, ProjectCandidateSet, ProjectCandidateSignal, serialize_project_candidate_snapshot
from app.models.enums import EvidenceValidity, PolicyDecision, ProjectStatus, ProposalType, TransitionStatus
from app.services.policy import ProjectIdentityAuthorizationService
from app.services.policy.project_identity_authorization import AUTO_LINKED_AUDIT_EVENT


class FakeLineageRepository:
    def __init__(self, proposal, evidence=()) -> None:
        self.proposal = proposal
        self.evidence = tuple(evidence)
        self.evaluations = {}
        self.audits = []
        self.transitions = []

    def get_proposal_for_update(self, proposal_id):
        return self.proposal if self.proposal.id == proposal_id else None

    def get_policy_evaluation(self, *, ai_proposal_id, policy_version):
        return self.evaluations.get((ai_proposal_id, policy_version))

    def create_policy_evaluation(self, **values):
        evaluation = SimpleNamespace(id=uuid4(), **values)
        self.evaluations[(values["ai_proposal_id"], values["policy_version"])] = evaluation
        return evaluation

    def list_proposal_evidence(self, proposal_id):
        return list(self.evidence)

    def list_evidence_by_ids(self, evidence_ids):
        return [item for item in self.evidence if item.id in evidence_ids]

    def list_policy_evidence(self, _evaluation_id):
        return []

    def get_state_transition_for_update(self, **values):
        return next(
            (
                item
                for item in self.transitions
                if item.policy_evaluation_id == values["policy_evaluation_id"]
                and item.affected_entity_type == values["affected_entity_type"]
                and item.affected_entity_id == values["affected_entity_id"]
            ),
            None,
        )

    def create_transition(self, **values):
        transition = SimpleNamespace(
            id=uuid4(),
            status=TransitionStatus.PREVIEWED,
            applied_at=None,
            **values,
        )
        self.transitions.append(transition)
        return transition

    def mark_transition_applied(self, transition, *, applied_at):
        transition.status = TransitionStatus.APPLIED
        transition.applied_at = applied_at
        return transition

    def get_audit_event(self, *, event_type, policy_evaluation_id, project_id=None):
        return next(
            (
                item
                for item in self.audits
                if item.event_type == event_type
                and item.policy_evaluation_id == policy_evaluation_id
                and item.project_id == project_id
            ),
            None,
        )

    def create_audit_event(self, **values):
        values.setdefault("project_id", None)
        audit = SimpleNamespace(id=uuid4(), **values)
        self.audits.append(audit)
        return audit


class FakeRecordRepository:
    def __init__(self, records=()) -> None:
        self.records = {record.id: record for record in records}

    def get(self, record_id):
        return self.records.get(record_id)


class FakeProjectLinkRepository(FakeRecordRepository):
    def __init__(self, records=(), *, fail_on_project_id=None) -> None:
        super().__init__(records)
        self.approved = {}
        self.fail_on_project_id = fail_on_project_id

    def get_or_create_approved_link(self, *, correspondence_event_id, project_id):
        if project_id == self.fail_on_project_id:
            raise RuntimeError("link write failed")
        key = (correspondence_event_id, project_id)
        if key in self.approved:
            return self.approved[key], False
        link = SimpleNamespace(
            id=uuid4(),
            correspondence_event_id=correspondence_event_id,
            project_id=project_id,
        )
        self.approved[key] = link
        return link, True

    def get_approved_link(self, *, correspondence_event_id, project_id):
        return self.approved.get((correspondence_event_id, project_id))

    def list_approved_project_ids_for_event(self, correspondence_event_id):
        return [
            project_id
            for event_id, project_id in self.approved
            if event_id == correspondence_event_id
        ]


def _signal(
    signal_type: CandidateSignalType,
    value: str,
    *,
    source_record_id: UUID | None = None,
    source: CandidateSignalSource = CandidateSignalSource.CORRESPONDENCE_EVENT,
    evidence_item_id: UUID | None = None,
) -> ProjectCandidateSignal:
    return ProjectCandidateSignal(
        signal_type=signal_type,
        matched_value=value,
        source=source,
        source_record_id=source_record_id,
        evidence_item_id=evidence_item_id,
        exact=True,
    )


def _candidate(*signals: ProjectCandidateSignal) -> ProjectCandidate:
    project_id = uuid4()
    return ProjectCandidate(
        project_id=project_id,
        project_code=f"CODE-{str(project_id)[:8]}",
        project_name="Example Project",
        project_status=ProjectStatus.ACTIVE,
        signals=signals,
    )


def _reference(candidate: ProjectCandidate) -> CandidateSignalReference:
    signal = candidate.signals[0]
    return CandidateSignalReference(
        project_id=candidate.project_id,
        signal_type=signal.signal_type,
        matched_value=signal.matched_value,
        source=signal.source,
        source_record_id=signal.source_record_id,
        evidence_item_id=signal.evidence_item_id,
    )


def _resolution(
    status: ResolutionStatus,
    *candidates: ProjectCandidate,
) -> ProjectResolution:
    if status is ResolutionStatus.NO_MATCH:
        return ProjectResolution(
            status=status,
            concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
        )
    return ProjectResolution(
        status=status,
        project_ids=tuple(candidate.project_id for candidate in candidates),
        evidence=tuple(
            ResolutionEvidence(
                project_id=candidate.project_id,
                signal_references=(_reference(candidate),),
                interpretation="The message appears to concern this project.",
            )
            for candidate in candidates
        ),
    )


def _proposal(
    candidates: tuple[ProjectCandidate, ...],
    resolution: ProjectResolution,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        correspondence_event_id=uuid4(),
        proposal_type=ProposalType.PROJECT_RESOLUTION,
        input_metadata=serialize_project_candidate_snapshot(
            ProjectCandidateSet(candidates=candidates)
        ),
        structured_output=resolution.model_dump(mode="json"),
    )


def _strong_candidate(code: str):
    contact_id = uuid4()
    candidate = _candidate(
        _signal(CandidateSignalType.PROJECT_CODE, code),
        _signal(
            CandidateSignalType.PROJECT_CONTACT,
            "sender@example.test",
            source_record_id=contact_id,
            source=CandidateSignalSource.PROJECT_RECORD,
        ),
    )
    contact = SimpleNamespace(
        id=contact_id,
        project_id=candidate.project_id,
        email_normalized="sender@example.test",
        is_active=True,
    )
    return candidate, contact


def _service(proposal, *, contacts=(), evidence=(), link_repository=None):
    session = MagicMock(spec=Session)
    lineage = FakeLineageRepository(proposal, evidence)
    links = link_repository or FakeProjectLinkRepository()
    service = ProjectIdentityAuthorizationService(
        session=session,
        lineage_repository=lineage,
        project_identifier_repository=FakeRecordRepository(),
        project_contact_repository=FakeRecordRepository(contacts),
        project_link_repository=links,
    )
    return service, session, lineage, links


def test_allowed_single_project_is_linked_and_committed_once() -> None:
    candidate, contact = _strong_candidate("CODE-1")
    proposal = _proposal(
        (candidate,),
        _resolution(ResolutionStatus.MATCHED, candidate),
    )
    service, session, lineage, links = _service(proposal, contacts=(contact,))

    result = service.authorize(proposal.id)

    assert result.evaluation.decision is PolicyDecision.ALLOW_AUTO_ACTION
    assert len(result.project_links) == 1
    assert len(result.created_project_link_ids) == 1
    assert len(lineage.evaluations) == 1
    assert len(lineage.audits) == 2
    assert len(lineage.transitions) == 1
    assert lineage.transitions[0].status is TransitionStatus.APPLIED
    assert len(links.approved) == 1
    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()


def test_allowed_multi_project_links_are_created_together() -> None:
    first, first_contact = _strong_candidate("CODE-1")
    second, second_contact = _strong_candidate("CODE-2")
    proposal = _proposal(
        (first, second),
        _resolution(ResolutionStatus.MULTI_PROJECT, first, second),
    )
    service, session, lineage, links = _service(
        proposal,
        contacts=(first_contact, second_contact),
    )

    result = service.authorize(proposal.id)

    assert result.evaluation.decision is PolicyDecision.ALLOW_AUTO_ACTION
    assert len(result.project_links) == 2
    assert len(result.created_project_link_ids) == 2
    assert len(lineage.audits) == 3
    assert len(lineage.transitions) == 1
    assert len(links.approved) == 2
    session.commit.assert_called_once_with()


@pytest.mark.parametrize("status", [ResolutionStatus.MATCHED, ResolutionStatus.NO_MATCH])
def test_review_and_no_match_create_no_authoritative_link(status) -> None:
    if status is ResolutionStatus.NO_MATCH:
        candidates = ()
        resolution = _resolution(status)
        contacts = ()
    else:
        contact_id = uuid4()
        candidate = _candidate(
            _signal(
                CandidateSignalType.PROJECT_CONTACT,
                "sender@example.test",
                source_record_id=contact_id,
                source=CandidateSignalSource.PROJECT_RECORD,
            )
        )
        candidates = (candidate,)
        resolution = _resolution(status, candidate)
        contacts = (
            SimpleNamespace(
                id=contact_id,
                project_id=candidate.project_id,
                email_normalized="sender@example.test",
                is_active=True,
            ),
        )
    proposal = _proposal(candidates, resolution)
    service, session, lineage, links = _service(proposal, contacts=contacts)

    result = service.authorize(proposal.id)

    assert result.evaluation.decision is PolicyDecision.REVIEW_REQUIRED
    assert result.project_links == ()
    assert links.approved == {}
    assert len(lineage.audits) == 1
    session.commit.assert_called_once_with()


def test_rejected_policy_creates_no_authoritative_link() -> None:
    evidence_id = uuid4()
    candidate = _candidate(
        _signal(
            CandidateSignalType.PROJECT_CODE,
            "CODE-1",
            source=CandidateSignalSource.EVIDENCE_ITEM,
            evidence_item_id=evidence_id,
        )
    )
    proposal = _proposal(
        (candidate,),
        _resolution(ResolutionStatus.MATCHED, candidate),
    )
    evidence = SimpleNamespace(
        id=evidence_id,
        validity=EvidenceValidity.INVALIDATED,
    )
    service, session, lineage, links = _service(proposal, evidence=(evidence,))

    result = service.authorize(proposal.id)

    assert result.evaluation.decision is PolicyDecision.REJECT_PROPOSAL
    assert result.project_links == ()
    assert links.approved == {}
    session.commit.assert_called_once_with()


def test_missing_candidate_snapshot_is_persisted_as_rejected() -> None:
    candidate = _candidate(_signal(CandidateSignalType.PROJECT_CODE, "CODE-1"))
    proposal = _proposal(
        (candidate,),
        _resolution(ResolutionStatus.MATCHED, candidate),
    )
    proposal.input_metadata = {}
    service, session, _, links = _service(proposal)

    result = service.authorize(proposal.id)

    assert result.evaluation.decision is PolicyDecision.REJECT_PROPOSAL
    assert result.evaluation.triggered_rule_ids == [
        "PID-002-CANDIDATE-SNAPSHOT-MISSING"
    ]
    assert links.approved == {}
    session.commit.assert_called_once_with()


def test_retry_reuses_evaluation_links_and_audits() -> None:
    candidate, contact = _strong_candidate("CODE-1")
    proposal = _proposal(
        (candidate,),
        _resolution(ResolutionStatus.MATCHED, candidate),
    )
    service, session, lineage, links = _service(proposal, contacts=(contact,))

    first = service.authorize(proposal.id)
    repeated = service.authorize(proposal.id)

    assert first.policy_evaluation_created is True
    assert repeated.policy_evaluation_created is False
    assert repeated.created_project_link_ids == ()
    assert len(lineage.evaluations) == 1
    assert len(links.approved) == 1
    assert len(lineage.audits) == 2
    assert len(lineage.transitions) == 1
    assert session.commit.call_count == 2
    session.rollback.assert_not_called()


def test_link_failure_rolls_back_without_commit() -> None:
    first, first_contact = _strong_candidate("CODE-1")
    second, second_contact = _strong_candidate("CODE-2")
    proposal = _proposal(
        (first, second),
        _resolution(ResolutionStatus.MULTI_PROJECT, first, second),
    )
    failing_links = FakeProjectLinkRepository(
        fail_on_project_id=second.project_id
    )
    service, session, _, _ = _service(
        proposal,
        contacts=(first_contact, second_contact),
        link_repository=failing_links,
    )

    with pytest.raises(RuntimeError, match="link write failed"):
        service.authorize(proposal.id)

    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()


def test_existing_links_are_preserved_but_only_missing_links_are_recorded_as_added() -> None:
    first, first_contact = _strong_candidate("CODE-1")
    second, second_contact = _strong_candidate("CODE-2")
    proposal = _proposal(
        (first, second),
        _resolution(ResolutionStatus.MULTI_PROJECT, first, second),
    )
    links = FakeProjectLinkRepository()
    existing, _ = links.get_or_create_approved_link(
        correspondence_event_id=proposal.correspondence_event_id,
        project_id=first.project_id,
    )
    service, _, lineage, _ = _service(
        proposal,
        contacts=(first_contact, second_contact),
        link_repository=links,
    )

    result = service.authorize(proposal.id)

    assert len(result.project_links) == 2
    assert result.project_links[0] is existing
    assert len(result.created_project_link_ids) == 1
    transition = lineage.transitions[0]
    assert transition.current_state["project_ids"] == [str(first.project_id)]
    assert transition.proposed_state["authorized_project_ids"] == [
        str(first.project_id),
        str(second.project_id),
    ]
    assert transition.proposed_state["added_project_ids"] == [str(second.project_id)]
    assert set(transition.proposed_state["project_ids"]) == {
        str(first.project_id),
        str(second.project_id),
    }
    created_audits = [
        item for item in lineage.audits if item.event_type == AUTO_LINKED_AUDIT_EVENT
    ]
    assert [item.project_id for item in created_audits] == [second.project_id]
    assert created_audits[0].state_transition_id == transition.id


def test_all_authorized_links_already_exist_is_a_true_noop() -> None:
    candidate, contact = _strong_candidate("CODE-1")
    proposal = _proposal(
        (candidate,),
        _resolution(ResolutionStatus.MATCHED, candidate),
    )
    links = FakeProjectLinkRepository()
    existing, _ = links.get_or_create_approved_link(
        correspondence_event_id=proposal.correspondence_event_id,
        project_id=candidate.project_id,
    )
    service, _, lineage, _ = _service(
        proposal,
        contacts=(contact,),
        link_repository=links,
    )

    result = service.authorize(proposal.id)

    assert result.project_links == (existing,)
    assert result.created_project_link_ids == ()
    assert result.transition is None
    assert lineage.transitions == []
    assert [item.event_type for item in lineage.audits] == [
        "project_identity_policy_evaluated"
    ]
