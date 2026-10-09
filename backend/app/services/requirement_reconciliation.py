import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from pydantic_ai import Agent

from app.ai.prompts.requirement_reconciler import REQUIREMENT_RECONCILER_PROMPT_VERSION
from app.ai.requirement_schemas import ExistingEvidenceReference, RequirementCorrectionKind, RequirementEvidenceReference, RequirementImpactDisposition, RequirementReconciliation, RequirementSourceEvidence
from app.ai.schemas import ResolverSourceField
from app.contracts.requirement_reconciliation import RequirementAttachmentContext, RequirementReconcilerInput, serialize_requirement_context_snapshot
from app.models.ai_proposal import AIProposal
from app.models.enums import ProposalType, RequirementState
from app.repositories.lineage import LineageRepository


class RequirementReconciliationValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedRequirementSourceEvidence:
    evidence: RequirementSourceEvidence
    start_offset: int
    end_offset: int
    page_number: int | None
    section: str | None


@dataclass(frozen=True)
class RequirementReconciliationResult:
    reconciliation: RequirementReconciliation
    validated_source_evidence: tuple[ValidatedRequirementSourceEvidence, ...]
    proposal: AIProposal


class RequirementReconciliationService:
    def __init__(
        self,
        *,
        agent: Agent[None, RequirementReconciliation],
        lineage_repository: LineageRepository,
        model_identifier: str,
    ) -> None:
        if not model_identifier.strip():
            raise ValueError("model_identifier must not be blank")
        self.agent = agent
        self.lineage_repository = lineage_repository
        self.model_identifier = model_identifier.strip()

    async def reconcile(
        self,
        context: RequirementReconcilerInput,
    ) -> RequirementReconciliationResult:
        run_result = await self.agent.run(context.model_dump_json())
        reconciliation = run_result.output
        validated_evidence = self._validate(context, reconciliation)
        evidence_item_ids = self._persist_evidence(
            context,
            reconciliation,
            validated_evidence,
        )
        input_payload = context.model_dump(mode="json")
        input_hash = hashlib.sha256(
            json.dumps(
                input_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        proposal = self.lineage_repository.create_proposal(
            correspondence_event_id=context.correspondence.correspondence_event_id,
            proposal_type=ProposalType.REQUIREMENT_RECONCILIATION,
            model_identifier=self.model_identifier,
            prompt_version=REQUIREMENT_RECONCILER_PROMPT_VERSION,
            input_hash=input_hash,
            input_metadata={
                "schema_version": 1,
                "project_id": str(context.project_id),
                "authoritative_project_link_id": str(
                    context.authoritative_project_link_id
                ),
                **serialize_requirement_context_snapshot(context),
            },
            structured_output=reconciliation.model_dump(mode="json"),
            evidence_item_ids=evidence_item_ids,
        )
        self.lineage_repository.create_audit_event(
            event_type="requirement_reconciliation_proposed",
            actor_type="system",
            correspondence_event_id=context.correspondence.correspondence_event_id,
            project_id=context.project_id,
            ai_proposal_id=proposal.id,
            details={
                "existing_impact_count": len(reconciliation.existing_impacts),
                "new_requirement_count": len(reconciliation.new_requirements),
                "correction_count": len(reconciliation.corrections),
                "concern_count": len(reconciliation.concerns),
                "conflict_count": len(reconciliation.conflicts),
                "model_identifier": self.model_identifier,
                "prompt_version": REQUIREMENT_RECONCILER_PROMPT_VERSION,
            },
        )
        return RequirementReconciliationResult(
            reconciliation=reconciliation,
            validated_source_evidence=validated_evidence,
            proposal=proposal,
        )

    def _persist_evidence(
        self,
        context: RequirementReconcilerInput,
        reconciliation: RequirementReconciliation,
        validated_source_evidence: tuple[ValidatedRequirementSourceEvidence, ...],
    ) -> list[UUID]:
        validated_by_key = {
            self._source_key(item.evidence): item
            for item in validated_source_evidence
        }
        created: dict[tuple[object, ...], UUID] = {}
        evidence_item_ids = []
        seen_ids: set[UUID] = set()
        for reference, requirement_id in self._scoped_evidence_references(
            reconciliation
        ):
            if isinstance(reference, ExistingEvidenceReference):
                evidence_id = reference.evidence_item_id
            else:
                source_key = self._source_key(reference)
                creation_key = (*source_key, requirement_id)
                evidence_id = created.get(creation_key)
                if evidence_id is None:
                    validated = validated_by_key[source_key]
                    evidence = self.lineage_repository.create_evidence(
                        correspondence_event_id=(
                            context.correspondence.correspondence_event_id
                        ),
                        attachment_id=reference.attachment_id,
                        project_id=context.project_id,
                        requirement_id=requirement_id,
                        source_type=reference.source_field.value.lower(),
                        excerpt=reference.excerpt,
                        page_number=validated.page_number,
                        section=validated.section,
                        provenance_metadata={
                            "source_field": reference.source_field.value,
                            "start_offset": validated.start_offset,
                            "end_offset": validated.end_offset,
                        },
                    )
                    evidence_id = evidence.id
                    created[creation_key] = evidence_id
            if evidence_id not in seen_ids:
                seen_ids.add(evidence_id)
                evidence_item_ids.append(evidence_id)
        return evidence_item_ids

    @staticmethod
    def _source_key(
        evidence: RequirementSourceEvidence,
    ) -> tuple[object, ...]:
        return (
            evidence.correspondence_event_id,
            evidence.source_field,
            evidence.attachment_id,
            evidence.excerpt,
        )

    @staticmethod
    def _scoped_evidence_references(
        reconciliation: RequirementReconciliation,
    ) -> tuple[tuple[RequirementEvidenceReference, UUID | None], ...]:
        references = []
        references.extend(
            (evidence, impact.requirement_id)
            for impact in reconciliation.existing_impacts
            for evidence in impact.evidence
        )
        references.extend(
            (evidence, correction.requirement_id)
            for correction in reconciliation.corrections
            for evidence in correction.evidence
        )
        references.extend(
            (ExistingEvidenceReference(evidence_item_id=evidence_id), correction.requirement_id)
            for correction in reconciliation.corrections
            for evidence_id in correction.target_evidence_item_ids
        )
        references.extend(
            (evidence, None)
            for proposal in reconciliation.new_requirements
            for evidence in proposal.evidence
        )
        references.extend(
            (
                evidence,
                concern.candidate_requirement_ids[0]
                if len(concern.candidate_requirement_ids) == 1
                else None,
            )
            for concern in reconciliation.concerns
            for evidence in concern.evidence
        )
        references.extend(
            (
                evidence,
                conflict.requirement_ids[0]
                if len(conflict.requirement_ids) == 1
                else None,
            )
            for conflict in reconciliation.conflicts
            for evidence in conflict.evidence
        )
        return tuple(references)

    def _validate(
        self,
        context: RequirementReconcilerInput,
        reconciliation: RequirementReconciliation,
    ) -> tuple[ValidatedRequirementSourceEvidence, ...]:
        requirements = {
            requirement.requirement_id: requirement
            for requirement in context.requirements
        }
        referenced_requirement_ids = {
            impact.requirement_id for impact in reconciliation.existing_impacts
        }
        referenced_requirement_ids.update(
            correction.requirement_id for correction in reconciliation.corrections
        )
        referenced_requirement_ids.update(
            requirement_id
            for concern in reconciliation.concerns
            for requirement_id in concern.candidate_requirement_ids
        )
        referenced_requirement_ids.update(
            requirement_id
            for conflict in reconciliation.conflicts
            for requirement_id in conflict.requirement_ids
        )
        if not referenced_requirement_ids.issubset(requirements):
            raise RequirementReconciliationValidationError(
                "reconciler returned a requirement outside the supplied project context"
            )

        for impact in reconciliation.existing_impacts:
            if impact.disposition is not RequirementImpactDisposition.UPDATE_PROPOSED:
                continue
            current = requirements[impact.requirement_id]
            if current.current_state is RequirementState.RETRACTED:
                raise RequirementReconciliationValidationError(
                    "ordinary impacts cannot reactivate a retracted requirement"
                )
            state_changed = (
                impact.proposed_state is not None
                and impact.proposed_state is not current.current_state
            )
            date_changed = (
                impact.proposed_expected_date is not None
                and impact.proposed_expected_date != current.expected_date
            )
            if not state_changed and not date_changed:
                raise RequirementReconciliationValidationError(
                    "UPDATE_PROPOSED must change the current state or expected date"
                )

        supplied_evidence = {
            evidence.evidence_item_id: evidence
            for evidence in context.existing_valid_evidence
        }
        for correction in reconciliation.corrections:
            current = requirements[correction.requirement_id]
            if current.current_state is RequirementState.RETRACTED:
                raise RequirementReconciliationValidationError(
                    "a retracted requirement cannot be corrected or withdrawn again"
                )
            if (
                correction.previous_state is not current.current_state
                or correction.previous_expected_date != current.expected_date
            ):
                raise RequirementReconciliationValidationError(
                    "correction previous values do not match supplied requirement"
                )
            if correction.kind is RequirementCorrectionKind.CORRECTION and (
                correction.proposed_state in (None, current.current_state)
                and correction.proposed_expected_date in (None, current.expected_date)
            ):
                raise RequirementReconciliationValidationError(
                    "CORRECTION must change the current state or expected date"
                )
            for evidence_id in correction.target_evidence_item_ids:
                prior = supplied_evidence.get(evidence_id)
                if prior is None or prior.requirement_id != correction.requirement_id:
                    raise RequirementReconciliationValidationError(
                        "correction target evidence was not supplied for the requirement"
                    )

        supplied_evidence_ids = {
            evidence.evidence_item_id
            for evidence in context.existing_valid_evidence
        }
        validated_source_evidence = []
        for evidence in self._evidence_references(reconciliation):
            if isinstance(evidence, ExistingEvidenceReference):
                if evidence.evidence_item_id not in supplied_evidence_ids:
                    raise RequirementReconciliationValidationError(
                        "reconciler referenced evidence that was not supplied"
                    )
                continue
            validated_source_evidence.append(
                self._locate_source_evidence(context, evidence)
            )
        return tuple(validated_source_evidence)

    @staticmethod
    def _evidence_references(
        reconciliation: RequirementReconciliation,
    ) -> tuple[RequirementEvidenceReference, ...]:
        references = []
        references.extend(
            evidence
            for impact in reconciliation.existing_impacts
            for evidence in impact.evidence
        )
        references.extend(
            evidence
            for proposal in reconciliation.new_requirements
            for evidence in proposal.evidence
        )
        references.extend(
            evidence
            for correction in reconciliation.corrections
            for evidence in correction.evidence
        )
        references.extend(
            evidence
            for concern in reconciliation.concerns
            for evidence in concern.evidence
        )
        references.extend(
            evidence
            for conflict in reconciliation.conflicts
            for evidence in conflict.evidence
        )
        return tuple(references)

    @classmethod
    def _locate_source_evidence(
        cls,
        context: RequirementReconcilerInput,
        evidence: RequirementSourceEvidence,
    ) -> ValidatedRequirementSourceEvidence:
        if (
            evidence.correspondence_event_id
            != context.correspondence.correspondence_event_id
        ):
            raise RequirementReconciliationValidationError(
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
            raise RequirementReconciliationValidationError(
                "evidence source text is not available"
            )
        offsets = cls._all_occurrences(source_text, evidence.excerpt)
        if not offsets:
            raise RequirementReconciliationValidationError(
                "evidence excerpt does not occur in the persisted source text"
            )
        if len(offsets) != 1:
            raise RequirementReconciliationValidationError(
                "evidence excerpt occurs more than once and is ambiguous"
            )
        start_offset = offsets[0]
        end_offset = start_offset + len(evidence.excerpt)
        page_number, section = cls._extraction_provenance(
            attachment,
            start_offset,
            end_offset,
        )
        return ValidatedRequirementSourceEvidence(
            evidence=evidence,
            start_offset=start_offset,
            end_offset=end_offset,
            page_number=page_number,
            section=section,
        )

    @staticmethod
    def _all_occurrences(source_text: str, excerpt: str) -> tuple[int, ...]:
        offsets = []
        start = 0
        while (offset := source_text.find(excerpt, start)) >= 0:
            offsets.append(offset)
            start = offset + 1
        return tuple(offsets)

    @staticmethod
    def _extraction_provenance(
        attachment: RequirementAttachmentContext | None,
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
