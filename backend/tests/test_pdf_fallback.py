from hashlib import sha256
from uuid import uuid4

import pytest

from app.contracts.attachment_content import HashedAttachmentContent
from app.contracts.attachment_extraction import AttachmentExtractionMetadata, ExtractionBounds, ExtractionMethod, ExtractionReason
from app.models.attachment import Attachment
from app.models.enums import AttachmentProcessingState
from app.services.pdf_fallback import PDFFallbackEligibilityError, build_pdf_fallback_request


def _bounds() -> ExtractionBounds:
    return ExtractionBounds(
        attachment_max_size_bytes=100,
        pdf_max_pages=10,
        extraction_max_characters=1_000,
        docx_max_paragraphs=100,
        docx_max_tables=10,
        docx_max_table_cells=100,
    )


def _eligible():
    attachment_id = uuid4()
    data = b"pdf bytes"
    digest = sha256(data).hexdigest()
    metadata = AttachmentExtractionMetadata(
        extraction_method=ExtractionMethod.PYMUPDF,
        reason=ExtractionReason.PDF_IMAGE_ONLY,
        truncated=False,
        processed_unit_count=1,
        bounds=_bounds(),
    )
    attachment = Attachment(
        id=attachment_id,
        correspondence_event_id=uuid4(),
        source_attachment_id="api:1",
        filename="scan.pdf",
        mime_type="application/pdf",
        size_bytes=len(data),
        content_hash=digest,
        extraction_metadata=metadata.model_dump(mode="json"),
        processing_state=AttachmentProcessingState.FALLBACK_REQUIRED,
    )
    content = HashedAttachmentContent(
        attachment_id=attachment_id,
        content=data,
        size_bytes=len(data),
        content_hash=digest,
    )
    return attachment, content


def test_builds_request_only_from_eligible_persisted_pdf() -> None:
    attachment, content = _eligible()

    request = build_pdf_fallback_request(attachment, content)

    assert request.attachment_id == attachment.id
    assert request.content == content.content
    assert request.reason is ExtractionReason.PDF_IMAGE_ONLY


@pytest.mark.parametrize(
    "mutation",
    [
        {"processing_state": AttachmentProcessingState.EXTRACTED},
        {"mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        {"filename": "scan.docx"},
        {"extraction_metadata": None},
    ],
)
def test_rejects_ineligible_persisted_state(mutation: dict[str, object]) -> None:
    attachment, content = _eligible()
    for name, value in mutation.items():
        setattr(attachment, name, value)

    with pytest.raises(PDFFallbackEligibilityError):
        build_pdf_fallback_request(attachment, content)


def test_rejects_wrong_attachment_hash_and_tampered_bytes() -> None:
    attachment, content = _eligible()
    wrong_identity = content.model_copy(update={"attachment_id": uuid4()})
    tampered = content.model_copy(update={"content": b"tampered", "size_bytes": 8})

    with pytest.raises(PDFFallbackEligibilityError):
        build_pdf_fallback_request(attachment, wrong_identity)
    with pytest.raises(PDFFallbackEligibilityError):
        build_pdf_fallback_request(attachment, tampered)
