import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from pydantic_ai import Agent

from app.ai.prompts.project_resolver import PROJECT_RESOLVER_PROMPT_VERSION
from app.ai.schemas import CandidateSignalReference, ProjectResolution, ProjectResolverInput, ResolutionConcern, ResolutionStatus, ResolverAttachment, ResolverSourceField, SourceTextEvidence
from app.contracts.project_candidate import ProjectCandidateSignal, serialize_project_candidate_snapshot
from app.models.ai_proposal import AIProposal
from app.models.enums import ProposalType
from app.repositories.lineage import LineageRepository

DETERMINISTIC_NO_CANDIDATES_MODEL = "deterministic:no-candidates"


class ProjectResolutionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ProjectResolutionResult:
    resolution: ProjectResolution
    proposal: AIProposal
    agent_invoked: bool


class ProjectResolutionService:
    def __init__(
        self,
        *,
        agent: Agent[None, ProjectResolution],
        lineage_repository: LineageRepository,
        model_identifier: str,
    ) -> None:
        if not model_identifier.strip():
            raise ValueError("model_identifier must not be blank")
        self.agent = agent
        self.lineage_repository = lineage_repository
        self.model_identifier = model_identifier.strip()

    async def resolve(
        self,
        context: ProjectResolverInput,
    ) -> ProjectResolutionResult:
        agent_invoked = bool(context.candidates.candidates)
        if agent_invoked:
            run_result = await self.agent.run(context.model_dump_json())
            resolution = run_result.output
            model_identifier = self.model_identifier
        else:
            resolution = ProjectResolution(
                status=ResolutionStatus.NO_MATCH,
                concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
            )
            model_identifier = DETERMINISTIC_NO_CANDIDATES_MODEL

        self._validate_resolution(context, resolution)
        evidence_item_ids = self._persist_evidence(context, resolution)
        input_payload = context.model_dump(mode="json")
        input_hash = hashlib.sha256(
            json.dumps(
                input_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        proposal = self.lineage_repository.create_proposal(
            correspondence_event_id=context.correspondence.correspondence_event_id,
            proposal_type=ProposalType.PROJECT_RESOLUTION,
            model_identifier=model_identifier,
            prompt_version=PROJECT_RESOLVER_PROMPT_VERSION,
            input_hash=input_hash,
            input_metadata={
                "schema_version": 1,
                "agent_invoked": agent_invoked,
                "candidate_project_ids": [
                    str(candidate.project_id)
                    for candidate in context.candidates.candidates
                ],
                "attachment_ids": [
                    str(attachment.attachment_id)
                    for attachment in context.attachments
                ],
                **serialize_project_candidate_snapshot(context.candidates),
            },
            structured_output=resolution.model_dump(mode="json"),
            evidence_item_ids=evidence_item_ids,
        )
        self.lineage_repository.create_audit_event(
            event_type="project_resolution_proposed",
            actor_type="system",
            correspondence_event_id=context.correspondence.correspondence_event_id,
            ai_proposal_id=proposal.id,
            details={
                "status": resolution.status.value,
                "project_ids": [str(project_id) for project_id in resolution.project_ids],
                "agent_invoked": agent_invoked,
                "model_identifier": model_identifier,
                "prompt_version": PROJECT_RESOLVER_PROMPT_VERSION,
            },
        )
        return ProjectResolutionResult(
            resolution=resolution,
            proposal=proposal,
            agent_invoked=agent_invoked,
        )

    def _validate_resolution(
        self,
        context: ProjectResolverInput,
        resolution: ProjectResolution,
    ) -> None:
        candidates = {
            candidate.project_id: candidate
            for candidate in context.candidates.candidates
        }
        unknown_projects = set(resolution.project_ids) - set(candidates)
        if unknown_projects:
            raise ProjectResolutionValidationError(
                "resolver returned a project outside the supplied candidate set"
            )

        for reference in self._signal_references(resolution):
            candidate = candidates.get(reference.project_id)
            if candidate is None or not any(
                self._matches_signal(reference, signal)
                for signal in candidate.signals
            ):
                raise ProjectResolutionValidationError(
                    "resolver returned a candidate signal that was not supplied"
                )

        for source_evidence in self._source_evidence(resolution):
            self._locate_excerpt(context, source_evidence)

    def _persist_evidence(
        self,
        context: ProjectResolverInput,
        resolution: ProjectResolution,
    ) -> list[UUID]:
        evidence_item_ids: list[UUID] = []
        seen_ids: set[UUID] = set()
        created_source_evidence: dict[tuple, UUID] = {}
        created_signal_evidence: dict[tuple, UUID] = {}

        for reference in self._signal_references(resolution):
            if reference.evidence_item_id is not None:
                evidence_id = reference.evidence_item_id
            else:
                key = (
                    reference.project_id,
                    reference.signal_type,
                    reference.matched_value,
                    reference.source,
                    reference.identifier_type,
                    reference.source_record_id,
                    reference.attachment_id,
                )
                evidence_id = created_signal_evidence.get(key)
                if evidence_id is None:
                    evidence = self.lineage_repository.create_evidence(
                        correspondence_event_id=(
                            context.correspondence.correspondence_event_id
                        ),
                        attachment_id=reference.attachment_id,
                        source_type=f"candidate_signal:{reference.signal_type.value.lower()}",
                        excerpt=reference.matched_value,
                        normalized_value=reference.matched_value,
                        provenance_metadata={
                            "candidate_project_id": str(reference.project_id),
                            "signal_source": reference.source.value,
                            "identifier_type": reference.identifier_type,
                            "source_record_id": (
                                str(reference.source_record_id)
                                if reference.source_record_id is not None
                                else None
                            ),
                        },
                    )
                    evidence_id = evidence.id
                    created_signal_evidence[key] = evidence_id
            if evidence_id not in seen_ids:
                seen_ids.add(evidence_id)
                evidence_item_ids.append(evidence_id)

        for source_evidence in self._source_evidence(resolution):
            key = (
                source_evidence.correspondence_event_id,
                source_evidence.source_field,
                source_evidence.attachment_id,
                source_evidence.excerpt,
            )
            evidence_id = created_source_evidence.get(key)
            if evidence_id is None:
                start_offset, end_offset, attachment = self._locate_excerpt(
                    context,
                    source_evidence,
                )
                page_number, section = self._existing_extraction_provenance(
                    attachment,
                    start_offset,
                    end_offset,
                )
                evidence = self.lineage_repository.create_evidence(
                    correspondence_event_id=(
                        context.correspondence.correspondence_event_id
                    ),
                    attachment_id=source_evidence.attachment_id,
                    source_type=source_evidence.source_field.value.lower(),
                    excerpt=source_evidence.excerpt,
                    page_number=page_number,
                    section=section,
                    provenance_metadata={
                        "source_field": source_evidence.source_field.value,
                        "start_offset": start_offset,
                        "end_offset": end_offset,
                    },
                )
                evidence_id = evidence.id
                created_source_evidence[key] = evidence_id
            if evidence_id not in seen_ids:
                seen_ids.add(evidence_id)
                evidence_item_ids.append(evidence_id)
        return evidence_item_ids

    @staticmethod
    def _signal_references(
        resolution: ProjectResolution,
    ) -> tuple[CandidateSignalReference, ...]:
        return tuple(
            reference
            for item in (*resolution.evidence, *resolution.conflicts)
            for reference in item.signal_references
        )

    @staticmethod
    def _source_evidence(
        resolution: ProjectResolution,
    ) -> tuple[SourceTextEvidence, ...]:
        return tuple(
            evidence
            for item in (*resolution.evidence, *resolution.conflicts)
            for evidence in item.source_evidence
        )

    @staticmethod
    def _matches_signal(
        reference: CandidateSignalReference,
        signal: ProjectCandidateSignal,
    ) -> bool:
        return (
            reference.signal_type is signal.signal_type
            and reference.matched_value == signal.matched_value
            and reference.source is signal.source
            and reference.identifier_type == signal.identifier_type
            and reference.source_record_id == signal.source_record_id
            and reference.attachment_id == signal.attachment_id
            and reference.evidence_item_id == signal.evidence_item_id
        )

    @staticmethod
    def _locate_excerpt(
        context: ProjectResolverInput,
        evidence: SourceTextEvidence,
    ) -> tuple[int, int, ResolverAttachment | None]:
        if (
            evidence.correspondence_event_id
            != context.correspondence.correspondence_event_id
        ):
            raise ProjectResolutionValidationError(
                "evidence references a different correspondence event"
            )

        attachment = None
        if evidence.source_field is ResolverSourceField.SUBJECT:
            source_text = context.correspondence.subject
        elif evidence.source_field is ResolverSourceField.BODY:
            source_text = context.correspondence.body
        else:
            attachment = next(
                (
                    item
                    for item in context.attachments
                    if item.attachment_id == evidence.attachment_id
                ),
                None,
            )
            source_text = attachment.extracted_text if attachment is not None else None

        if source_text is None:
            raise ProjectResolutionValidationError(
                "evidence source text is not available"
            )
        offsets = ProjectResolutionService._all_occurrences(
            source_text,
            evidence.excerpt,
        )
        if not offsets:
            raise ProjectResolutionValidationError(
                "evidence excerpt does not occur in the persisted source text"
            )
        if len(offsets) != 1:
            raise ProjectResolutionValidationError(
                "evidence excerpt occurs more than once and is ambiguous"
            )
        start_offset = offsets[0]
        return start_offset, start_offset + len(evidence.excerpt), attachment

    @staticmethod
    def _all_occurrences(source_text: str, excerpt: str) -> tuple[int, ...]:
        offsets = []
        start = 0
        while (offset := source_text.find(excerpt, start)) >= 0:
            offsets.append(offset)
            start = offset + 1
        return tuple(offsets)

    @staticmethod
    def _existing_extraction_provenance(
        attachment: ResolverAttachment | None,
        start_offset: int,
        end_offset: int,
    ) -> tuple[int | None, str | None]:
        if attachment is None or attachment.extraction_metadata is None:
            return None, None

        metadata = attachment.extraction_metadata
        for segment in metadata.get("pdf_segments", ()):
            if (
                isinstance(segment, dict)
                and segment.get("text_start", -1) <= start_offset
                and segment.get("text_end", -1) >= end_offset
            ):
                page_number = segment.get("page_number")
                return page_number if isinstance(page_number, int) else None, None

        for segment in metadata.get("docx_segments", ()):
            if not isinstance(segment, dict) or not (
                segment.get("text_start", -1) <= start_offset
                and segment.get("text_end", -1) >= end_offset
            ):
                continue
            paragraph = segment.get("paragraph_index")
            if isinstance(paragraph, int):
                return None, f"paragraph:{paragraph}"
            table = segment.get("table_index")
            row = segment.get("row_index")
            column = segment.get("column_index")
            if all(isinstance(value, int) for value in (table, row, column)):
                return None, f"table:{table}/row:{row}/column:{column}"
        return None, None
