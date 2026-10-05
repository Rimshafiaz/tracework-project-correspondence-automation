from datetime import date

import pytest
from pydantic import ValidationError

from app.contracts.project_setup import ProjectSetupRequest


def _payload() -> dict:
    return {
        "name": "Neutral Project",
        "identifiers": [
            {"identifier_type": "External Reference", "display_value": "REF-1"}
        ],
        "contacts": [
            {
                "email": "Trusted@Example.com",
                "display_name": "Trusted Contact",
            }
        ],
        "requirements": [
            {
                "name": "Initial approval",
                "expected_date": "2026-10-20",
            }
        ],
    }


def test_setup_contract_accepts_only_initial_configuration_fields() -> None:
    request = ProjectSetupRequest.model_validate(_payload())

    assert request.requirements[0].expected_date == date(2026, 10, 20)
    assert "state" not in request.requirements[0].model_fields_set


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("name",), " "),
        (("identifiers", 0, "identifier_type"), " "),
        (("identifiers", 0, "display_value"), " "),
        (("contacts", 0, "display_name"), " "),
        (("requirements", 0, "name"), " "),
    ],
)
def test_setup_contract_rejects_blank_required_text(path, value) -> None:
    payload = _payload()
    target = payload
    for item in path[:-1]:
        target = target[item]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        ProjectSetupRequest.model_validate(payload)


@pytest.mark.parametrize(
    "field",
    ["status", "verified", "is_active", "state"],
)
def test_server_controlled_fields_are_rejected(field: str) -> None:
    payload = _payload()
    if field == "status":
        payload[field] = "CLOSED"
    elif field == "verified":
        payload["identifiers"][0][field] = False
    elif field == "is_active":
        payload["contacts"][0][field] = False
    else:
        payload["requirements"][0][field] = "SATISFIED"

    with pytest.raises(ValidationError):
        ProjectSetupRequest.model_validate(payload)


def test_client_supplied_project_code_is_rejected() -> None:
    payload = _payload()
    payload["project_code"] = "TW-999"

    with pytest.raises(ValidationError):
        ProjectSetupRequest.model_validate(payload)


def test_invalid_email_and_date_are_rejected() -> None:
    bad_email = _payload()
    bad_email["contacts"][0]["email"] = "not-an-email"
    bad_date = _payload()
    bad_date["requirements"][0]["expected_date"] = "not-a-date"

    with pytest.raises(ValidationError):
        ProjectSetupRequest.model_validate(bad_email)
    with pytest.raises(ValidationError):
        ProjectSetupRequest.model_validate(bad_date)


@pytest.mark.parametrize("collection", ["identifiers", "contacts", "requirements"])
def test_normalized_duplicates_are_rejected(collection: str) -> None:
    payload = _payload()
    duplicate = dict(payload[collection][0])
    if collection == "identifiers":
        duplicate["identifier_type"] = " external reference "
        duplicate["display_value"] = " ref-1 "
    elif collection == "contacts":
        duplicate["email"] = " trusted@example.com "
    else:
        duplicate["name"] = " initial APPROVAL "
    payload[collection].append(duplicate)

    with pytest.raises(ValidationError):
        ProjectSetupRequest.model_validate(payload)
