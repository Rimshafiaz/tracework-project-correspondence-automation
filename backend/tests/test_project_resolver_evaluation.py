from app.contracts.project_candidate import CandidateSignalType
from app.evaluation.datasets import DatasetSplit, load_dataset
from app.evaluation.project_resolver import build_project_resolver_input


def test_development_cases_convert_to_bounded_resolver_context() -> None:
    cases = load_dataset(DatasetSplit.DEVELOPMENT)

    for case in cases:
        context, reverse_project_ids = build_project_resolver_input(case)

        assert len(context.candidates.candidates) == len(
            case.input.candidate_projects
        )
        assert set(reverse_project_ids.values()) == {
            project.project_id for project in case.input.candidate_projects
        }
        assert all(candidate.signals for candidate in context.candidates.candidates)


def test_evaluation_conversion_preserves_contact_and_identifier_signals() -> None:
    case = load_dataset(DatasetSplit.DEVELOPMENT)[0]

    context, _ = build_project_resolver_input(case)
    signal_types = {
        signal.signal_type
        for candidate in context.candidates.candidates
        for signal in candidate.signals
    }

    assert CandidateSignalType.VERIFIED_IDENTIFIER in signal_types
    assert CandidateSignalType.PROJECT_CONTACT in signal_types
