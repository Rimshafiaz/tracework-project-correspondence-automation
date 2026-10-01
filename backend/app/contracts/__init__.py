from app.contracts.attachment_content import AttachmentContent, HashedAttachmentContent
from app.contracts.attachment_extraction import AttachmentExtractionMetadata, AttachmentExtractionResult, DOCXTextSegment, ExtractionBounds, ExtractionMethod, ExtractionReason, GeminiPDFFallbackRequest, PDFTextSegment
from app.contracts.correspondence import NormalizedAttachment, NormalizedCorrespondenceEvent
from app.contracts.pdf_extraction import PDFExtraction, PDFPageExtraction
from app.contracts.transition_preview import PolicyEvaluationSnapshot, RequirementEffect, StateTransitionPreview, TransitionState

__all__ = [
    "AttachmentContent",
    "AttachmentExtractionMetadata",
    "AttachmentExtractionResult",
    "DOCXTextSegment",
    "ExtractionMethod",
    "ExtractionReason",
    "ExtractionBounds",
    "HashedAttachmentContent",
    "GeminiPDFFallbackRequest",
    "NormalizedAttachment",
    "NormalizedCorrespondenceEvent",
    "PDFExtraction",
    "PDFPageExtraction",
    "PDFTextSegment",
    "PolicyEvaluationSnapshot",
    "RequirementEffect",
    "StateTransitionPreview",
    "TransitionState",
]
