from uuid import uuid4

from app.contracts.attachment_content import AttachmentContent
from app.services.attachment_hashing import hash_attachment_content


def test_hashing_is_deterministic_and_preserves_content() -> None:
    content = AttachmentContent(
        attachment_id=uuid4(),
        content=b"same bytes",
        size_bytes=10,
    )

    first = hash_attachment_content(content)
    second = hash_attachment_content(content)

    assert first.content_hash == second.content_hash
    assert len(first.content_hash) == 64
    assert first.content_hash == first.content_hash.lower()
    assert set(first.content_hash) <= set("0123456789abcdef")
    assert first.content == content.content
    assert first.attachment_id == content.attachment_id


def test_different_and_empty_content_have_deterministic_hashes() -> None:
    attachment_id = uuid4()
    first = hash_attachment_content(
        AttachmentContent(
            attachment_id=attachment_id,
            content=b"first",
            size_bytes=5,
        )
    )
    second = hash_attachment_content(
        AttachmentContent(
            attachment_id=attachment_id,
            content=b"second",
            size_bytes=6,
        )
    )
    empty = hash_attachment_content(
        AttachmentContent(
            attachment_id=attachment_id,
            content=b"",
            size_bytes=0,
        )
    )

    assert first.content_hash != second.content_hash
    assert empty.content_hash == (
        "e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855"
    )
