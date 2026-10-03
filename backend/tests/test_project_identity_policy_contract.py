from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.schemas import ProjectResolution, ResolutionConcern, ResolutionStatus
from app.contracts.project_candidate import ProjectCandidateSet
from app.contracts.project_identity_policy import ProjectIdentityPolicyContext, ProjectIdentityPolicyResult, ProjectIdentityRule
from app.models.enums import PolicyDecision, ProposalType
from app.services.policy import PROJECT_IDENTITY_POLICY_VERSION, PROJECT_IDENTITY_RULE_REASONS, reason_for_project_identity_rule


def _no_match_context() -> ProjectIdentityPolicyContext:
    return ProjectIdentityPolicyContext(
        proposal_id=uuid4(),
        correspondence_event_id=uuid4(),
        proposal_type=ProposalType.PROJECT_RESOLUTION,
        resolution=ProjectResolution(
            status=ResolutionStatus.NO_MATCH,
            concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
        ),
        candidate_set=ProjectCandidateSet(),
    )


def test_policy_context_preserves_existing_m7_and_m8_contracts() -> None:
    context = _no_match_context()

    assert context.candidate_set == ProjectCandidateSet()
    assert context.resolution.status is ResolutionStatus.NO_MATCH
    assert context.proposal_type is ProposalType.PROJECT_RESOLUTION


def test_policy_context_rejects_duplicate_lineage_ids() -> None:
    evidence_id = uuid4()
    values = _no_match_context().model_dump()
    values["proposal_evidence_ids"] = (evidence_id, evidence_id)

    with pytest.raises(ValidationError, match="policy context IDs must be unique"):
        ProjectIdentityPolicyContext(**values)


def test_policy_result_serializes_stable_rule_ids_for_persistence() -> None:
    proposal_id = uuid4()
    evidence_id = uuid4()
    rule = ProjectIdentityRule.EXACT_PROJECT_CODE
    result = ProjectIdentityPolicyResult(
        proposal_id=proposal_id,
        resolver_status=ResolutionStatus.MATCHED,
        policy_version=PROJECT_IDENTITY_POLICY_VERSION,
        decision=PolicyDecision.REVIEW_REQUIRED,
        triggered_rule_ids=(rule,),
        reasons=(reason_for_project_identity_rule(rule),),
        evidence_ids=(evidence_id,),
    )

    payload = result.model_dump(mode="json")

    assert payload["triggered_rule_ids"] == ["PID-201-EXACT-PROJECT-CODE"]
    assert payload["policy_version"] == "project-identity/1"
    assert payload["evidence_ids"] == [str(evidence_id)]


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"policy_version": "  "}, "policy_version must not be blank"),
        ({"reasons": ("",)}, "policy reasons must not be blank"),
        (
            {
                "triggered_rule_ids": (
                    ProjectIdentityRule.EXACT_PROJECT_CODE,
                    ProjectIdentityRule.EXACT_PROJECT_CODE,
                ),
                "reasons": ("First", "Second"),
            },
            "policy result items must be unique",
        ),
        (
            {
                "triggered_rule_ids": (
                    ProjectIdentityRule.EXACT_PROJECT_CODE,
                    ProjectIdentityRule.KNOWN_PROJECT_CONTACT,
                ),
                "reasons": ("Only one reason",),
            },
            "each triggered policy rule requires one reason",
        ),
    ],
)
def test_policy_result_rejects_invalid_audit_data(
    changes: dict[str, object],
    message: str,
) -> None:
    values = {
        "proposal_id": uuid4(),
        "resolver_status": ResolutionStatus.MATCHED,
        "policy_version": PROJECT_IDENTITY_POLICY_VERSION,
        "decision": PolicyDecision.REVIEW_REQUIRED,
        "triggered_rule_ids": (ProjectIdentityRule.EXACT_PROJECT_CODE,),
        "reasons": ("An exact project code was found.",),
        "evidence_ids": (),
    }
    values.update(changes)

    with pytest.raises(ValidationError, match=message):
        ProjectIdentityPolicyResult(**values)


def test_every_rule_has_one_stable_nonblank_reason() -> None:
    assert len({rule.value for rule in ProjectIdentityRule}) == len(ProjectIdentityRule)
    assert set(PROJECT_IDENTITY_RULE_REASONS) == set(ProjectIdentityRule)
    assert all(reason.strip() for reason in PROJECT_IDENTITY_RULE_REASONS.values())
