from types import SimpleNamespace
from uuid import UUID

from app.ai.requirement_schemas import RequirementSourceEvidence
from app.ai.schemas import ResolutionStatus
from app.evaluation.datasets import DatasetSplit, load_dataset
from app.evaluation.contracts import EvaluationCaseResult
from app.evaluation.project_resolver import _fixture_uuid
from app.evaluation.runner import _capture
from app.evaluation.scoring import score_evaluation_case
from app.models.enums import EvidenceValidity, PolicyDecision, ProposalType


def test_capture_records_runtime_evidence_from_actual_proposal_association(monkeypatch):
    case = load_dataset(DatasetSplit.HELD_OUT)[6]
    project_id = _fixture_uuid("project", "larkhaven-pier")
    source_id = _fixture_uuid("correspondence", case.input.correspondence.external_event_id)
    proposal = SimpleNamespace(id=UUID("59dc18be-8d99-4200-88b2-d76a9c016d95"),
        proposal_type=ProposalType.REQUIREMENT_RECONCILIATION)
    project_proposal = SimpleNamespace(id=UUID("e4c327fc-783e-4227-99fb-fca1cc3ce7e0"),
        proposal_type=ProposalType.PROJECT_RESOLUTION)
    evidence = SimpleNamespace(id=UUID("234661c5-39b0-41f8-a776-b2e7f2206616"),
        correspondence_event_id=source_id, project_id=project_id, requirement_id=None,
        source_type="body", excerpt=case.input.correspondence.body, attachment_id=None,
        provenance_metadata=None, validity=EvidenceValidity.VALID)

    class Lineage:
        def __init__(self, session):
            pass

        def list_proposal_evidence(self, proposal_id):
            return [evidence] if proposal_id == proposal.id else []

    monkeypatch.setattr("app.evaluation.runner.LineageRepository", Lineage)
    rows = iter(([], [], [], [], [evidence]))
    session = SimpleNamespace(scalars=lambda statement: next(rows))
    resolution = SimpleNamespace(status=ResolutionStatus.MATCHED, project_ids=(project_id,), conflicts=())
    reconciliation = SimpleNamespace(new_requirements=(SimpleNamespace(name="Visitor access register",
        evidence=(RequirementSourceEvidence(correspondence_event_id=source_id, source_field="BODY",
            excerpt=evidence.excerpt),)),), conflicts=(), corrections=())
    policy = SimpleNamespace(decision=PolicyDecision.REVIEW_REQUIRED, policy_version="test",
        triggered_rule_ids=(), reasons=())
    actual = _capture(session, case, {project_id: "larkhaven-pier"}, resolution,
        project_proposal, proposal, policy, reconciliation)
    captured = actual.source_evidence[0]
    assert captured.correspondence_event_id == source_id
    assert captured.proposal_id == proposal.id
    assert captured.project_id == "larkhaven-pier"
    assert actual.new_requirements[0].evidence_ids == (captured.evidence_id,)
    result = EvaluationCaseResult(case_id=case.case_id, status="UNSCORED", actual=actual)
    assert score_evaluation_case(case, result).status.value == "PASS"
