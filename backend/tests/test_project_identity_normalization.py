import pytest

from app.normalization.project_identity import normalize_identifier, normalize_identifier_type, normalize_project_code, normalize_project_name


def test_project_code_and_name_normalization_is_deterministic() -> None:
    assert normalize_project_code("  PRJ-42  ") == "prj-42"
    assert normalize_project_name("  Example\tProject\nName  ") == "example project name"


def test_identifier_default_is_domain_neutral() -> None:
    assert normalize_identifier_type(" Client Reference ") == "client reference"
    assert (
        normalize_identifier("custom_reference", "  Reference  ABC  ")
        == "reference abc"
    )


def test_identifier_can_select_a_normalizer_by_stored_type() -> None:
    normalizers = {"case-sensitive-id": lambda value: value.replace(" ", "")}

    assert (
        normalize_identifier(
            "CASE-SENSITIVE-ID",
            " Ab C-123 ",
            type_normalizers=normalizers,
        )
        == "AbC-123"
    )


@pytest.mark.parametrize(
    ("normalizer", "value"),
    [
        (normalize_project_code, " "),
        (normalize_project_name, "\t"),
        (normalize_identifier_type, "\n"),
    ],
)
def test_identity_normalizers_reject_blank_values(normalizer, value: str) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        normalizer(value)


def test_identifier_rejects_blank_values() -> None:
    with pytest.raises(ValueError, match="identifier value"):
        normalize_identifier("alias", " ")
