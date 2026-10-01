from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AttachmentProcessingState


class ExtractionMethod(StrEnum):
    PYMUPDF = "PYMUPDF"
    PYTHON_DOCX = "PYTHON_DOCX"


class ExtractionReason(StrEnum):
    EMPTY_ATTACHMENT = "EMPTY_ATTACHMENT"
    ATTACHMENT_TOO_LARGE = "ATTACHMENT_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    CONTENT_TYPE_MISMATCH = "CONTENT_TYPE_MISMATCH"
    MALFORMED_PDF = "MALFORMED_PDF"
    ENCRYPTED_PDF = "ENCRYPTED_PDF"
    EMPTY_PDF = "EMPTY_PDF"
    PDF_IMAGE_ONLY = "PDF_IMAGE_ONLY"
    PDF_PARTIAL_IMAGE_TEXT = "PDF_PARTIAL_IMAGE_TEXT"
    MALFORMED_DOCX = "MALFORMED_DOCX"
    EMPTY_DOCX = "EMPTY_DOCX"
    EXTRACTION_LIMIT_REACHED = "EXTRACTION_LIMIT_REACHED"


class PDFTextSegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_number: int = Field(ge=1)
    text_start: int = Field(ge=0)
    text_end: int = Field(ge=0)
    text: str

    @model_validator(mode="after")
    def validate_offsets(self) -> "PDFTextSegment":
        if self.text_end - self.text_start != len(self.text):
            raise ValueError("PDF segment offsets must match its text length")
        return self


class DOCXTextSegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    paragraph_index: int | None = Field(default=None, ge=0)
    table_index: int | None = Field(default=None, ge=0)
    row_index: int | None = Field(default=None, ge=0)
    column_index: int | None = Field(default=None, ge=0)
    text_start: int = Field(ge=0)
    text_end: int = Field(ge=0)
    text: str

    @model_validator(mode="after")
    def validate_provenance(self) -> "DOCXTextSegment":
        is_paragraph = self.paragraph_index is not None
        is_table_cell = all(
            value is not None
            for value in (self.table_index, self.row_index, self.column_index)
        )
        if is_paragraph == is_table_cell:
            raise ValueError("DOCX segment must identify one paragraph or one table cell")
        if self.text_end - self.text_start != len(self.text):
            raise ValueError("DOCX segment offsets must match its text length")
        return self


class AttachmentExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: UUID
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: AttachmentProcessingState
    extraction_method: ExtractionMethod | None
    extracted_text: str | None
    pdf_segments: tuple[PDFTextSegment, ...] = ()
    docx_segments: tuple[DOCXTextSegment, ...] = ()
    reason: ExtractionReason | None = None
    truncated: bool = False
    source_size_bytes: int = Field(ge=0)
    processed_unit_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_pdf_result(self) -> "AttachmentExtractionResult":
        if self.status in {
            AttachmentProcessingState.EXTRACTED,
            AttachmentProcessingState.FALLBACK_REQUIRED,
        } and (self.extraction_method is None or self.content_hash is None):
            raise ValueError("successful or fallback extraction requires a method and hash")
        if (
            self.status is AttachmentProcessingState.EXTRACTED
            and self.extraction_method is ExtractionMethod.PYMUPDF
        ):
            if not self.extracted_text or not self.pdf_segments:
                raise ValueError("extracted PDF requires text and provenance segments")
        if (
            self.status is AttachmentProcessingState.EXTRACTED
            and self.extraction_method is ExtractionMethod.PYTHON_DOCX
        ):
            if not self.extracted_text or not self.docx_segments:
                raise ValueError("extracted DOCX requires text and provenance segments")
        if self.status is AttachmentProcessingState.FALLBACK_REQUIRED:
            if self.extraction_method is not ExtractionMethod.PYMUPDF or self.reason not in {
                ExtractionReason.PDF_IMAGE_ONLY,
                ExtractionReason.PDF_PARTIAL_IMAGE_TEXT,
            }:
                raise ValueError("PDF fallback requires PyMuPDF and an image-related reason")
        if self.extracted_text:
            for segment in (*self.pdf_segments, *self.docx_segments):
                if self.extracted_text[segment.text_start : segment.text_end] != segment.text:
                    raise ValueError("segment offsets must point to extracted text")
        if self.pdf_segments and self.docx_segments:
            raise ValueError("an extraction result cannot mix PDF and DOCX segments")
        if self.status in {
            AttachmentProcessingState.FAILED,
            AttachmentProcessingState.UNSUPPORTED,
        } and self.reason is None:
            raise ValueError("failed or unsupported extraction requires a reason")
        return self


class ExtractionBounds(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_max_size_bytes: int = Field(gt=0)
    pdf_max_pages: int = Field(gt=0)
    extraction_max_characters: int = Field(gt=0)
    docx_max_paragraphs: int = Field(gt=0)
    docx_max_tables: int = Field(gt=0)
    docx_max_table_cells: int = Field(gt=0)


class AttachmentExtractionMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    extraction_method: ExtractionMethod | None
    reason: ExtractionReason | None
    truncated: bool
    processed_unit_count: int = Field(ge=0)
    bounds: ExtractionBounds
    pdf_segments: tuple[PDFTextSegment, ...] = ()
    docx_segments: tuple[DOCXTextSegment, ...] = ()


class GeminiPDFFallbackRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: bytes
    reason: ExtractionReason
    partial_extracted_text: str | None
    pdf_segments: tuple[PDFTextSegment, ...] = ()

    @model_validator(mode="after")
    def validate_reason(self) -> "GeminiPDFFallbackRequest":
        if self.reason not in {
            ExtractionReason.PDF_IMAGE_ONLY,
            ExtractionReason.PDF_PARTIAL_IMAGE_TEXT,
        }:
            raise ValueError("Gemini PDF fallback requires an image-related reason")
        return self
