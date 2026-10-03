from app.contracts.attachment_content import AttachmentContent, HashedAttachmentContent
from app.contracts.attachment_extraction import AttachmentExtractionMetadata, AttachmentExtractionResult, DOCXTextSegment, ExtractionBounds, ExtractionMethod, ExtractionReason, GeminiPDFFallbackRequest, PDFTextSegment
from app.contracts.correspondence import NormalizedAttachment, NormalizedCorrespondenceEvent
from app.contracts.pdf_extraction import PDFExtraction, PDFPageExtraction
from app.contracts.project_candidate import CandidateIdentifierHint, CandidateSetCardinality, CandidateSignalSource, CandidateSignalType, CandidateValueHint, FuzzyCandidateOptions, PROJECT_CANDIDATE_SNAPSHOT_SCHEMA_VERSION, ProjectCandidate, ProjectCandidateQuery, ProjectCandidateSet, ProjectCandidateSignal, ProjectCandidateSnapshotError, reconstruct_project_candidate_snapshot, serialize_project_candidate_snapshot
from app.contracts.transition_preview import PolicyEvaluationSnapshot, RequirementEffect, StateTransitionPreview, TransitionState

__all__ = [
    "AttachmentContent",
    "AttachmentExtractionMetadata",
    "AttachmentExtractionResult",
    "CandidateIdentifierHint",
    "CandidateSetCardinality",
    "CandidateSignalSource",
    "CandidateSignalType",
    "CandidateValueHint",
    "DOCXTextSegment",
    "ExtractionMethod",
    "ExtractionReason",
    "ExtractionBounds",
    "FuzzyCandidateOptions",
    "HashedAttachmentContent",
    "GeminiPDFFallbackRequest",
    "NormalizedAttachment",
    "NormalizedCorrespondenceEvent",
    "PDFExtraction",
    "PDFPageExtraction",
    "PDFTextSegment",
    "PolicyEvaluationSnapshot",
    "PROJECT_CANDIDATE_SNAPSHOT_SCHEMA_VERSION",
    "ProjectCandidate",
    "ProjectCandidateQuery",
    "ProjectCandidateSet",
    "ProjectCandidateSignal",
    "ProjectCandidateSnapshotError",
    "RequirementEffect",
    "StateTransitionPreview",
    "TransitionState",
    "reconstruct_project_candidate_snapshot",
    "serialize_project_candidate_snapshot",
]
