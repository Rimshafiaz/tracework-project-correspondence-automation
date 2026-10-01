from uuid import uuid4

import pymupdf
import pytest

from app.contracts.attachment_content import HashedAttachmentContent
from app.services.attachment_hashing import hash_attachment_content
from app.services.pdf_extraction import PDFExtractionError, PDFExtractionFailure, extract_pdf


def _pdf(*page_texts: str, encrypted: bool = False) -> bytes:
    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    options = (
        {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "owner_pw": "owner", "user_pw": "secret"}
        if encrypted
        else {}
    )
    data = document.tobytes(**options)
    document.close()
    return data


def _content(data: bytes) -> HashedAttachmentContent:
    from app.contracts.attachment_content import AttachmentContent

    return hash_attachment_content(
        AttachmentContent(attachment_id=uuid4(), content=data, size_bytes=len(data))
    )


def _extract(data: bytes, **limits: int):
    return extract_pdf(
        _content(data),
        filename="evidence.PDF",
        mime_type="APPLICATION/PDF",
        max_pages=limits.get("max_pages", 250),
        max_characters=limits.get("max_characters", 1_000_000),
    )


def test_extracts_pages_with_exact_text_offsets() -> None:
    result = _extract(_pdf("First page", "Second page"))

    assert result.extracted_text == "First page\n\nSecond page"
    assert [page.page_number for page in result.pages] == [1, 2]
    assert [(page.text_start, page.text_end) for page in result.pages] == [(0, 10), (12, 23)]
    assert all(result.extracted_text[page.text_start : page.text_end] == page.text for page in result.pages)
    assert result.total_page_count == result.processed_page_count == 2
    assert result.truncated is False


def test_preserves_blank_page_provenance() -> None:
    result = _extract(_pdf("", "Text"))

    assert result.extracted_text == "Text"
    assert result.pages[0].text == ""
    assert result.pages[0].text_start == result.pages[0].text_end == 0
    assert result.pages[1].text_start == 0


def test_reports_embedded_images() -> None:
    document = pymupdf.open()
    page = document.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1, 1), False)
    pixmap.clear_with(255)
    page.insert_image(pymupdf.Rect(0, 0, 10, 10), pixmap=pixmap)
    data = document.tobytes()
    document.close()

    assert _extract(data).pages[0].has_embedded_images is True


def test_page_and_character_limits_are_bounded() -> None:
    page_limited = _extract(_pdf("one", "two", "three"), max_pages=2)
    character_limited = _extract(_pdf("abcdef", "second"), max_characters=3)

    assert page_limited.processed_page_count == 2
    assert page_limited.total_page_count == 3
    assert page_limited.truncated is True
    assert character_limited.extracted_text == "abc"
    assert character_limited.pages[0].text == "abc"
    assert character_limited.processed_page_count == 1
    assert character_limited.truncated is True


@pytest.mark.parametrize(
    ("filename", "mime_type"),
    [("file.txt", "application/pdf"), ("file.pdf", "text/plain")],
)
def test_rejects_content_type_mismatch(filename: str, mime_type: str) -> None:
    with pytest.raises(PDFExtractionError) as raised:
        extract_pdf(
            _content(_pdf("text")),
            filename=filename,
            mime_type=mime_type,
            max_pages=1,
            max_characters=10,
        )

    assert raised.value.reason is PDFExtractionFailure.CONTENT_TYPE_MISMATCH


def test_rejects_malformed_and_encrypted_pdfs() -> None:
    with pytest.raises(PDFExtractionError) as malformed:
        _extract(b"not a PDF")
    with pytest.raises(PDFExtractionError) as encrypted:
        _extract(_pdf("secret", encrypted=True))

    assert malformed.value.reason is PDFExtractionFailure.MALFORMED_PDF
    assert encrypted.value.reason is PDFExtractionFailure.ENCRYPTED_PDF


def test_rejects_nonpositive_limits() -> None:
    with pytest.raises(ValueError, match="limits must be positive"):
        _extract(_pdf("text"), max_pages=0)
