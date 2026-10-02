from rapidfuzz import fuzz, process

from app.contracts.project_candidate import CandidateIdentifierHint, CandidateSignalSource, CandidateSignalType, CandidateValueHint, FuzzyCandidateOptions, ProjectCandidate, ProjectCandidateQuery, ProjectCandidateSet, ProjectCandidateSignal
from app.normalization.correspondence import normalize_email, normalize_source
from app.normalization.project_identity import normalize_identifier, normalize_identifier_type, normalize_project_code, normalize_project_name
from app.repositories.project import ProjectRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository

PROJECT_ALIAS_IDENTIFIER_TYPE = "alias"


class ProjectCandidateConflict(ValueError):
    pass


def retrieve_project_code_candidates(
    query: ProjectCandidateQuery,
    repository: ProjectRepository,
) -> ProjectCandidateSet:
    hints_by_code: dict[str, list[CandidateValueHint]] = {}
    seen_hints: set[tuple] = set()
    for hint in query.project_codes:
        code = normalize_project_code(hint.normalized_value)
        hint_key = (code, hint.source, hint.attachment_id, hint.evidence_item_id)
        if hint_key in seen_hints:
            continue
        seen_hints.add(hint_key)
        hints_by_code.setdefault(code, []).append(hint)

    projects = repository.find_by_normalized_codes(set(hints_by_code))
    candidates = []
    for project in projects:
        normalized_code = normalize_project_code(project.project_code)
        signals = tuple(
            ProjectCandidateSignal(
                signal_type=CandidateSignalType.PROJECT_CODE,
                matched_value=normalized_code,
                source=hint.source,
                attachment_id=hint.attachment_id,
                evidence_item_id=hint.evidence_item_id,
                exact=True,
            )
            for hint in hints_by_code.get(normalized_code, ())
        )
        if signals:
            candidates.append(
                ProjectCandidate(
                    project_id=project.id,
                    project_code=project.project_code,
                    project_name=project.name,
                    project_status=project.status,
                    signals=signals,
                )
            )
    return ProjectCandidateSet(candidates=tuple(candidates))


def retrieve_verified_identifier_candidates(
    query: ProjectCandidateQuery,
    repository: ProjectIdentifierRepository,
) -> ProjectCandidateSet:
    hints_by_identifier: dict[tuple[str, str], list[CandidateIdentifierHint]] = {}
    seen_hints: set[tuple] = set()
    for hint in query.identifiers:
        if hint.source in {
            CandidateSignalSource.ATTACHMENT,
            CandidateSignalSource.EVIDENCE_ITEM,
        }:
            continue
        identifier_type = normalize_identifier_type(hint.identifier_type)
        normalized_value = normalize_identifier(identifier_type, hint.normalized_value)
        identifier = (identifier_type, normalized_value)
        hint_key = (*identifier, hint.source, hint.attachment_id, hint.evidence_item_id)
        if hint_key in seen_hints:
            continue
        seen_hints.add(hint_key)
        hints_by_identifier.setdefault(identifier, []).append(hint)

    matches = repository.find_verified_exact_with_projects(set(hints_by_identifier))
    projects_by_id: dict = {}
    signals_by_project_id: dict = {}
    for identifier, project in matches:
        if not identifier.verified:
            continue
        key = (identifier.identifier_type, identifier.normalized_value)
        hints = hints_by_identifier.get(key, ())
        if not hints:
            continue
        projects_by_id[project.id] = project
        project_signals = signals_by_project_id.setdefault(project.id, [])
        project_signals.extend(
            ProjectCandidateSignal(
                signal_type=CandidateSignalType.VERIFIED_IDENTIFIER,
                matched_value=identifier.normalized_value,
                source=hint.source,
                identifier_type=identifier.identifier_type,
                attachment_id=hint.attachment_id,
                evidence_item_id=hint.evidence_item_id,
                exact=True,
                verified=True,
            )
            for hint in hints
        )

    return ProjectCandidateSet(
        candidates=tuple(
            ProjectCandidate(
                project_id=project.id,
                project_code=project.project_code,
                project_name=project.name,
                project_status=project.status,
                signals=tuple(signals_by_project_id[project.id]),
            )
            for project in projects_by_id.values()
        )
    )


def retrieve_document_identifier_candidates(
    query: ProjectCandidateQuery,
    repository: ProjectIdentifierRepository,
) -> ProjectCandidateSet:
    hints_by_identifier: dict[tuple[str, str], list[CandidateIdentifierHint]] = {}
    seen_hints: set[tuple] = set()
    for hint in query.identifiers:
        if hint.source not in {
            CandidateSignalSource.ATTACHMENT,
            CandidateSignalSource.EVIDENCE_ITEM,
        }:
            continue
        identifier_type = normalize_identifier_type(hint.identifier_type)
        normalized_value = normalize_identifier(identifier_type, hint.normalized_value)
        identifier = (identifier_type, normalized_value)
        hint_key = (*identifier, hint.source, hint.attachment_id, hint.evidence_item_id)
        if hint_key in seen_hints:
            continue
        seen_hints.add(hint_key)
        hints_by_identifier.setdefault(identifier, []).append(hint)

    matches = repository.find_verified_exact_with_projects(set(hints_by_identifier))
    projects_by_id: dict = {}
    signals_by_project_id: dict = {}
    for identifier, project in matches:
        if not identifier.verified:
            continue
        key = (identifier.identifier_type, identifier.normalized_value)
        hints = hints_by_identifier.get(key, ())
        if not hints:
            continue
        projects_by_id[project.id] = project
        signals_by_project_id.setdefault(project.id, []).extend(
            ProjectCandidateSignal(
                signal_type=CandidateSignalType.DOCUMENT_IDENTIFIER,
                matched_value=identifier.normalized_value,
                source=hint.source,
                identifier_type=identifier.identifier_type,
                attachment_id=hint.attachment_id,
                evidence_item_id=hint.evidence_item_id,
                exact=True,
                verified=True,
            )
            for hint in hints
        )

    return ProjectCandidateSet(
        candidates=tuple(
            ProjectCandidate(
                project_id=project.id,
                project_code=project.project_code,
                project_name=project.name,
                project_status=project.status,
                signals=tuple(signals_by_project_id[project.id]),
            )
            for project in projects_by_id.values()
        )
    )


def retrieve_name_and_alias_candidates(
    query: ProjectCandidateQuery,
    project_repository: ProjectRepository,
    identifier_repository: ProjectIdentifierRepository,
) -> ProjectCandidateSet:
    hints_by_name: dict[str, list[CandidateValueHint]] = {}
    seen_hints: set[tuple] = set()
    for hint in query.normalized_names:
        normalized_name = normalize_project_name(hint.normalized_value)
        hint_key = (
            normalized_name,
            hint.source,
            hint.attachment_id,
            hint.evidence_item_id,
        )
        if hint_key in seen_hints:
            continue
        seen_hints.add(hint_key)
        hints_by_name.setdefault(normalized_name, []).append(hint)

    names = set(hints_by_name)
    projects = project_repository.find_by_normalized_names(names)
    alias_matches = identifier_repository.find_verified_exact_with_projects(
        {(PROJECT_ALIAS_IDENTIFIER_TYPE, name) for name in names}
    )
    projects_by_id: dict = {}
    signals_by_project_id: dict = {}

    for project in projects:
        hints = hints_by_name.get(project.normalized_name, ())
        if not hints:
            continue
        projects_by_id[project.id] = project
        signals_by_project_id.setdefault(project.id, []).extend(
            ProjectCandidateSignal(
                signal_type=CandidateSignalType.NORMALIZED_NAME,
                matched_value=project.normalized_name,
                source=hint.source,
                attachment_id=hint.attachment_id,
                evidence_item_id=hint.evidence_item_id,
                exact=True,
            )
            for hint in hints
        )

    for identifier, project in alias_matches:
        if (
            not identifier.verified
            or identifier.identifier_type != PROJECT_ALIAS_IDENTIFIER_TYPE
        ):
            continue
        hints = hints_by_name.get(identifier.normalized_value, ())
        if not hints:
            continue
        projects_by_id[project.id] = project
        signals_by_project_id.setdefault(project.id, []).extend(
            ProjectCandidateSignal(
                signal_type=CandidateSignalType.ALIAS,
                matched_value=identifier.normalized_value,
                source=hint.source,
                identifier_type=identifier.identifier_type,
                attachment_id=hint.attachment_id,
                evidence_item_id=hint.evidence_item_id,
                exact=True,
                verified=True,
            )
            for hint in hints
        )

    return ProjectCandidateSet(
        candidates=tuple(
            ProjectCandidate(
                project_id=project.id,
                project_code=project.project_code,
                project_name=project.name,
                project_status=project.status,
                signals=tuple(signals_by_project_id[project.id]),
            )
            for project in projects_by_id.values()
        )
    )


def retrieve_contact_candidates(
    query: ProjectCandidateQuery,
    repository: ProjectContactRepository,
) -> ProjectCandidateSet:
    if query.sender_email_normalized is None:
        return ProjectCandidateSet()

    sender_email = normalize_email(query.sender_email_normalized)
    candidates = []
    seen_project_ids = set()
    for contact, project in repository.find_active_with_projects(sender_email):
        if not contact.is_active or project.id in seen_project_ids:
            continue
        seen_project_ids.add(project.id)
        candidates.append(
            ProjectCandidate(
                project_id=project.id,
                project_code=project.project_code,
                project_name=project.name,
                project_status=project.status,
                signals=(
                    ProjectCandidateSignal(
                        signal_type=CandidateSignalType.PROJECT_CONTACT,
                        matched_value=sender_email,
                        source=CandidateSignalSource.PROJECT_RECORD,
                        exact=True,
                    ),
                ),
            )
        )
    return ProjectCandidateSet(candidates=tuple(candidates))


def retrieve_conversation_candidates(
    query: ProjectCandidateQuery,
    repository: CorrespondenceProjectLinkRepository,
) -> ProjectCandidateSet:
    if query.external_conversation_id is None:
        return ProjectCandidateSet()

    source = normalize_source(query.source)
    conversation_id = query.external_conversation_id.strip()
    candidates = []
    seen_project_ids = set()
    projects = repository.find_approved_projects_for_conversation(
        source=source,
        external_conversation_id=conversation_id,
    )
    for project in projects:
        if project.id in seen_project_ids:
            continue
        seen_project_ids.add(project.id)
        candidates.append(
            ProjectCandidate(
                project_id=project.id,
                project_code=project.project_code,
                project_name=project.name,
                project_status=project.status,
                signals=(
                    ProjectCandidateSignal(
                        signal_type=CandidateSignalType.APPROVED_CONVERSATION,
                        matched_value=conversation_id,
                        source=CandidateSignalSource.APPROVED_CONVERSATION_LINK,
                        exact=True,
                        previously_approved=True,
                    ),
                ),
            )
        )
    return ProjectCandidateSet(candidates=tuple(candidates))


def retrieve_fuzzy_name_alias_candidates(
    query: ProjectCandidateQuery,
    project_repository: ProjectRepository,
    identifier_repository: ProjectIdentifierRepository,
    options: FuzzyCandidateOptions,
) -> ProjectCandidateSet:
    if not query.normalized_names:
        return ProjectCandidateSet()

    entries = [
        (CandidateSignalType.FUZZY_NAME, project.normalized_name, project, None)
        for project in project_repository.list_for_fuzzy_name_retrieval()
    ]
    entries.extend(
        (CandidateSignalType.FUZZY_ALIAS, identifier.normalized_value, project, "alias")
        for identifier, project in identifier_repository.list_verified_type_with_projects(
            PROJECT_ALIAS_IDENTIFIER_TYPE
        )
        if identifier.verified
        and identifier.identifier_type == PROJECT_ALIAS_IDENTIFIER_TYPE
    )
    choices = [entry[1] for entry in entries]
    projects_by_id: dict = {}
    signals_by_project_id: dict = {}
    signal_keys: set[tuple] = set()

    for hint in query.normalized_names:
        normalized_hint = normalize_project_name(hint.normalized_value)
        selected_project_ids = set()
        matches = process.extract(
            normalized_hint,
            choices,
            scorer=fuzz.WRatio,
            score_cutoff=options.minimum_score,
            limit=None,
        )
        for _, score, entry_index in matches:
            if score == 100:
                continue
            signal_type, matched_value, project, identifier_type = entries[entry_index]
            if (
                project.id not in selected_project_ids
                and len(selected_project_ids) == options.max_candidates_per_hint
            ):
                continue
            selected_project_ids.add(project.id)
            signal_key = (
                project.id,
                signal_type,
                matched_value,
                hint.source,
                hint.attachment_id,
                hint.evidence_item_id,
            )
            if signal_key in signal_keys:
                continue
            signal_keys.add(signal_key)
            projects_by_id[project.id] = project
            signals_by_project_id.setdefault(project.id, []).append(
                ProjectCandidateSignal(
                    signal_type=signal_type,
                    matched_value=matched_value,
                    source=hint.source,
                    identifier_type=identifier_type,
                    attachment_id=hint.attachment_id,
                    evidence_item_id=hint.evidence_item_id,
                    exact=False,
                    verified=signal_type is CandidateSignalType.FUZZY_ALIAS,
                    similarity_score=score,
                )
            )

    ordered_projects = sorted(
        projects_by_id.values(),
        key=lambda project: (project.project_code.casefold(), str(project.id)),
    )
    return ProjectCandidateSet(
        candidates=tuple(
            ProjectCandidate(
                project_id=project.id,
                project_code=project.project_code,
                project_name=project.name,
                project_status=project.status,
                signals=tuple(signals_by_project_id[project.id]),
            )
            for project in ordered_projects
        )
    )


def merge_project_candidate_sets(
    *candidate_sets: ProjectCandidateSet,
) -> ProjectCandidateSet:
    candidates_by_id: dict = {}
    signals_by_project_id: dict = {}
    signal_keys_by_project_id: dict = {}

    for candidate_set in candidate_sets:
        for candidate in candidate_set.candidates:
            existing = candidates_by_id.get(candidate.project_id)
            if existing is not None and (
                existing.project_code != candidate.project_code
                or existing.project_name != candidate.project_name
                or existing.project_status is not candidate.project_status
            ):
                raise ProjectCandidateConflict(
                    f"Conflicting identity for project {candidate.project_id}"
                )
            candidates_by_id[candidate.project_id] = candidate
            signals = signals_by_project_id.setdefault(candidate.project_id, [])
            signal_keys = signal_keys_by_project_id.setdefault(candidate.project_id, set())
            for signal in candidate.signals:
                signal_key = (
                    signal.signal_type,
                    signal.matched_value,
                    signal.source,
                    signal.identifier_type,
                    signal.attachment_id,
                    signal.evidence_item_id,
                    signal.exact,
                    signal.verified,
                    signal.previously_approved,
                    signal.similarity_score,
                )
                if signal_key not in signal_keys:
                    signal_keys.add(signal_key)
                    signals.append(signal)

    ordered_candidates = sorted(
        candidates_by_id.values(),
        key=lambda candidate: (
            candidate.project_code.casefold(),
            str(candidate.project_id),
        ),
    )
    return ProjectCandidateSet(
        candidates=tuple(
            candidate.model_copy(
                update={"signals": tuple(signals_by_project_id[candidate.project_id])}
            )
            for candidate in ordered_candidates
        )
    )


def retrieve_project_candidates(
    query: ProjectCandidateQuery,
    *,
    project_repository: ProjectRepository,
    identifier_repository: ProjectIdentifierRepository,
    contact_repository: ProjectContactRepository,
    conversation_repository: CorrespondenceProjectLinkRepository,
    fuzzy_options: FuzzyCandidateOptions | None = None,
) -> ProjectCandidateSet:
    candidate_sets = [
        retrieve_project_code_candidates(query, project_repository),
        retrieve_verified_identifier_candidates(query, identifier_repository),
        retrieve_name_and_alias_candidates(
            query,
            project_repository,
            identifier_repository,
        ),
        retrieve_contact_candidates(query, contact_repository),
        retrieve_conversation_candidates(query, conversation_repository),
        retrieve_document_identifier_candidates(query, identifier_repository),
    ]
    if fuzzy_options is not None:
        candidate_sets.append(
            retrieve_fuzzy_name_alias_candidates(
                query,
                project_repository,
                identifier_repository,
                fuzzy_options,
            )
        )
    return merge_project_candidate_sets(*candidate_sets)
