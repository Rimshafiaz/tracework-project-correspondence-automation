from datetime import date

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator

from app.normalization.correspondence import normalize_email
from app.normalization.project_identity import (
    normalize_identifier,
    normalize_identifier_type,
    normalize_project_name,
)


class ProjectSetupIdentifier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    identifier_type: str
    display_value: str

    @field_validator("identifier_type", "display_value")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("identifier fields must not be blank")
        return value


class ProjectSetupContact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    email: EmailStr
    display_name: str
    role: str | None = None

    @field_validator("display_name")
    @classmethod
    def reject_blank_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("contact display name must not be blank")
        return value

    @field_validator("role")
    @classmethod
    def normalize_optional_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ProjectSetupRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str | None = None
    expected_date: date | None = None

    @field_validator("name")
    @classmethod
    def reject_blank_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("requirement name must not be blank")
        return value

    @field_validator("description")
    @classmethod
    def normalize_optional_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ProjectSetupRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    identifiers: tuple[ProjectSetupIdentifier, ...] = ()
    contacts: tuple[ProjectSetupContact, ...] = ()
    requirements: tuple[ProjectSetupRequirement, ...] = ()

    @field_validator("name")
    @classmethod
    def reject_blank_project_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("project name must not be blank")
        return value

    @model_validator(mode="after")
    def reject_duplicate_children(self) -> "ProjectSetupRequest":
        identifier_keys = [
            (
                normalize_identifier_type(item.identifier_type),
                normalize_identifier(item.identifier_type, item.display_value),
            )
            for item in self.identifiers
        ]
        if len(identifier_keys) != len(set(identifier_keys)):
            raise ValueError("setup identifiers must be unique after normalization")

        contact_keys = [normalize_email(str(item.email)) for item in self.contacts]
        if len(contact_keys) != len(set(contact_keys)):
            raise ValueError("setup contacts must be unique after normalization")

        requirement_keys = [
            normalize_project_name(item.name) for item in self.requirements
        ]
        if len(requirement_keys) != len(set(requirement_keys)):
            raise ValueError("setup requirement names must be unique after normalization")

        normalize_project_name(self.name)
        return self
