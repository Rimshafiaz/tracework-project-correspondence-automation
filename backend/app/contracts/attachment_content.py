from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AttachmentContent(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: UUID
    content: bytes
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_size(self) -> "AttachmentContent":
        if self.size_bytes != len(self.content):
            raise ValueError("size_bytes must equal the decoded content length")
        return self


class HashedAttachmentContent(AttachmentContent):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
