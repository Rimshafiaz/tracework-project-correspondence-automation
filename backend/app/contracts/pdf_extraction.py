from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PDFPageExtraction(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_number: int = Field(ge=1)
    text_start: int = Field(ge=0)
    text_end: int = Field(ge=0)
    text: str
    has_embedded_images: bool

    @model_validator(mode="after")
    def validate_offsets(self) -> "PDFPageExtraction":
        if self.text_end - self.text_start != len(self.text):
            raise ValueError("page offsets must match the page text length")
        return self


class PDFExtraction(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_size_bytes: int = Field(ge=0)
    extracted_text: str
    pages: tuple[PDFPageExtraction, ...]
    total_page_count: int = Field(ge=0)
    processed_page_count: int = Field(ge=0)
    truncated: bool

    @model_validator(mode="after")
    def validate_pages(self) -> "PDFExtraction":
        if self.processed_page_count != len(self.pages):
            raise ValueError("processed_page_count must equal the number of pages")
        for page in self.pages:
            if self.extracted_text[page.text_start : page.text_end] != page.text:
                raise ValueError("page offsets must point to page text")
        return self
