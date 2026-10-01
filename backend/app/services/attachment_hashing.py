from hashlib import sha256

from app.contracts.attachment_content import AttachmentContent, HashedAttachmentContent


def hash_attachment_content(content: AttachmentContent) -> HashedAttachmentContent:
    return HashedAttachmentContent(
        attachment_id=content.attachment_id,
        content=content.content,
        size_bytes=content.size_bytes,
        content_hash=sha256(content.content).hexdigest(),
    )
