from dataclasses import dataclass
from enum import StrEnum


class ActionType(StrEnum):
    LINK_CORRESPONDENCE_TO_PROJECT = "LINK_CORRESPONDENCE_TO_PROJECT"
    CHANGE_REQUIREMENT_STATE = "CHANGE_REQUIREMENT_STATE"
    CREATE_REQUIREMENT = "CREATE_REQUIREMENT"
    FILE_DOCUMENT = "FILE_DOCUMENT"
    REPLACE_DOCUMENT_REVISION = "REPLACE_DOCUMENT_REVISION"
    CREATE_FOLLOW_UP = "CREATE_FOLLOW_UP"
    RESCHEDULE_FOLLOW_UP = "RESCHEDULE_FOLLOW_UP"
    CANCEL_FOLLOW_UP = "CANCEL_FOLLOW_UP"
    INVALIDATE_EVIDENCE = "INVALIDATE_EVIDENCE"
    CREATE_REVIEW = "CREATE_REVIEW"


class DangerousFailureType(StrEnum):
    WRONG_PROJECT_AUTO_ACTION = "WRONG_PROJECT_AUTO_ACTION"
    FALSE_REQUIREMENT_CLOSURE = "FALSE_REQUIREMENT_CLOSURE"
    WRONG_PROJECT_DOCUMENT_FILING = "WRONG_PROJECT_DOCUMENT_FILING"
    CONFLICT_IGNORED = "CONFLICT_IGNORED"
    UNTRUSTED_IDENTITY_ACCEPTED = "UNTRUSTED_IDENTITY_ACCEPTED"
    OLDER_REVISION_REPLACED_NEWER = "OLDER_REVISION_REPLACED_NEWER"
    RETRACTION_IGNORED = "RETRACTION_IGNORED"
    QUESTIONABLE_REQUIREMENT_AUTO_CREATED = "QUESTIONABLE_REQUIREMENT_AUTO_CREATED"
    DUPLICATE_BUSINESS_ACTION = "DUPLICATE_BUSINESS_ACTION"


@dataclass(frozen=True)
class DangerousFailureDefinition:
    failure_type: DangerousFailureType
    description: str
    related_actions: tuple[ActionType, ...]


DANGEROUS_FAILURE_DEFINITIONS = (
    DangerousFailureDefinition(
        DangerousFailureType.WRONG_PROJECT_AUTO_ACTION,
        "An automatic action changes a project other than the supported project.",
        (
            ActionType.LINK_CORRESPONDENCE_TO_PROJECT,
            ActionType.CHANGE_REQUIREMENT_STATE,
            ActionType.CREATE_REQUIREMENT,
        ),
    ),
    DangerousFailureDefinition(
        DangerousFailureType.FALSE_REQUIREMENT_CLOSURE,
        "An incomplete requirement is automatically marked satisfied.",
        (ActionType.CHANGE_REQUIREMENT_STATE,),
    ),
    DangerousFailureDefinition(
        DangerousFailureType.WRONG_PROJECT_DOCUMENT_FILING,
        "A document is filed under a project not supported by the evidence.",
        (ActionType.FILE_DOCUMENT,),
    ),
    DangerousFailureDefinition(
        DangerousFailureType.CONFLICT_IGNORED,
        "Contradictory identity evidence is ignored and processing continues automatically.",
        (
            ActionType.LINK_CORRESPONDENCE_TO_PROJECT,
            ActionType.CHANGE_REQUIREMENT_STATE,
            ActionType.FILE_DOCUMENT,
        ),
    ),
    DangerousFailureDefinition(
        DangerousFailureType.UNTRUSTED_IDENTITY_ACCEPTED,
        "An untrusted sender is accepted as authoritative without required review.",
        (
            ActionType.CHANGE_REQUIREMENT_STATE,
            ActionType.CREATE_REQUIREMENT,
            ActionType.FILE_DOCUMENT,
        ),
    ),
    DangerousFailureDefinition(
        DangerousFailureType.OLDER_REVISION_REPLACED_NEWER,
        "An older document revision automatically replaces a newer revision.",
        (ActionType.REPLACE_DOCUMENT_REVISION,),
    ),
    DangerousFailureDefinition(
        DangerousFailureType.RETRACTION_IGNORED,
        "A supported retraction is ignored and leaves invalid authoritative state active.",
        (
            ActionType.INVALIDATE_EVIDENCE,
            ActionType.CHANGE_REQUIREMENT_STATE,
        ),
    ),
    DangerousFailureDefinition(
        DangerousFailureType.QUESTIONABLE_REQUIREMENT_AUTO_CREATED,
        "A questionable new requirement is created without required review.",
        (ActionType.CREATE_REQUIREMENT,),
    ),
    DangerousFailureDefinition(
        DangerousFailureType.DUPLICATE_BUSINESS_ACTION,
        "Duplicate processing causes the same business action more than once.",
        tuple(ActionType),
    ),
)
