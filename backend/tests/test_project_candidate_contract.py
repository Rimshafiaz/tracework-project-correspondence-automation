from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.project_candidate import CandidateIdentifierHint, CandidateSetCardinality, CandidateSignalSource, CandidateSignalType, CandidateValueHint, ProjectCandidate, ProjectCandidateQuery, ProjectCandidateSet, ProjectCandidateSignal
from app.models.enums import ProjectStatus


def _candidate(name: str = "Platform Modernization") -> ProjectCandidate:
    return ProjectCandidate(
        project_id=uuid4(),
        project_code="PLATFORM",
        project_name=name,
        project_status=ProjectStatus.ACTIVE,
        signals=(
            ProjectCandidateSignal(
                signal_type=CandidateSignalType.PROJECT_CODE,
                matched_value="PLATFORM",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
                exact=True,
            ),
        ),
    )


def test_query_is_channel_and_project_type_neutral() -> None:
    attachment_id = uuid4()
    query = ProjectCandidateQuery(
        source="fixture",
        external_conversation_id="conversation-1",
        sender_email_normalized=" Person@Example.COM ",
        project_codes=(
            CandidateValueHint(
                normalized_value="PLATFORM",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
        ),
        identifiers=(
            CandidateIdentifierHint(
                identifier_type="repository",
                normalized_value="example/platform",
                source=CandidateSignalSource.ATTACHMENT,
                attachment_id=attachment_id,
            ),
        ),
    )

    assert query.sender_email_normalized == "person@example.com"
    assert query.identifiers[0].identifier_type == "repository"
    assert "gmail" not in ProjectCandidateQuery.model_fields
    assert "address" not in ProjectCandidateQuery.model_fields


def test_candidate_preserves_multiple_inspectable_signals() -> None:
    candidate = _candidate().model_copy(
        update={
            "signals": (
                ProjectCandidateSignal(
                    signal_type=CandidateSignalType.VERIFIED_IDENTIFIER,
                    matched_value="example/platform",
                    source=CandidateSignalSource.EVIDENCE_ITEM,
                    identifier_type="repository",
                    evidence_item_id=uuid4(),
                    exact=True,
                    verified=True,
                ),
                ProjectCandidateSignal(
                    signal_type=CandidateSignalType.PROJECT_CONTACT,
                    matched_value="person@example.com",
                    source=CandidateSignalSource.PROJECT_RECORD,
                    exact=True,
                ),
            )
        }
    )

    assert len(candidate.signals) == 2
    assert candidate.signals[0].evidence_item_id is not None


def test_candidate_set_reports_cardinality_without_making_a_decision() -> None:
    empty = ProjectCandidateSet()
    single = ProjectCandidateSet(candidates=(_candidate(),))
    multiple = ProjectCandidateSet(candidates=(_candidate(), _candidate("Other Project")))

    assert empty.cardinality is CandidateSetCardinality.NONE
    assert single.cardinality is CandidateSetCardinality.SINGLE
    assert single.is_ambiguous is False
    assert multiple.cardinality is CandidateSetCardinality.MULTIPLE
    assert multiple.is_ambiguous is True
    assert "selected_project_id" not in ProjectCandidateSet.model_fields


def test_rejects_duplicate_candidates_and_invalid_signal_claims() -> None:
    candidate = _candidate()
    with pytest.raises(ValidationError, match="must be unique"):
        ProjectCandidateSet(candidates=(candidate, candidate))
    with pytest.raises(ValidationError, match="similarity score"):
        ProjectCandidateSignal(
            signal_type=CandidateSignalType.FUZZY_NAME,
            matched_value="Platform",
            source=CandidateSignalSource.PROJECT_RECORD,
            exact=False,
        )
    with pytest.raises(ValidationError, match="marked verified"):
        ProjectCandidateSignal(
            signal_type=CandidateSignalType.VERIFIED_IDENTIFIER,
            matched_value="external-1",
            source=CandidateSignalSource.PROJECT_RECORD,
            exact=True,
        )
    with pytest.raises(ValidationError, match="must be exact"):
        ProjectCandidateSignal(
            signal_type=CandidateSignalType.PROJECT_CONTACT,
            matched_value="person@example.com",
            source=CandidateSignalSource.PROJECT_RECORD,
            exact=False,
        )


@pytest.mark.parametrize("value", ["", "   "])
def test_rejects_blank_lookup_values(value: str) -> None:
    with pytest.raises(ValidationError):
        CandidateValueHint(
            normalized_value=value,
            source=CandidateSignalSource.CORRESPONDENCE_EVENT,
        )
