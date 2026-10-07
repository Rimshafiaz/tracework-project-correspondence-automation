import pytest

from app.contracts.document_revision import (
    DOCUMENT_REVISION_POLICY_VERSION,
    MAX_REVISION_ORDER,
    DocumentRevisionRule,
    RevisionOutcome,
    RevisionParseReason,
    RevisionParseStatus,
)
from app.normalization.document_revision import (
    compare_revision_orders,
    parse_document_revision,
)


@pytest.mark.parametrize(
    ("filename", "family", "raw", "normalized", "order"),
    [
        ("Structural Plan Rev 1.pdf", "structural plan", "Rev 1", "REV-1", 1),
        ("Structural Plan Rev 10.pdf", "structural plan", "Rev 10", "REV-10", 10),
        ("Structural Plan R2.pdf", "structural plan", "R2", "REV-2", 2),
        ("Structural Plan Revision 3.pdf", "structural plan", "Revision 3", "REV-3", 3),
        ("Structural_Plan-Rev_04.pdf", "structural plan", "Rev_04", "REV-4", 4),
        ("STRUCTURAL plan rEv-5.PDF", "structural plan", "rEv-5", "REV-5", 5),
        ("Ｓｔｒｕｃｔｕｒａｌ＿Ｐｌａｎ Rev ６.pdf", "structural plan", "Rev ６", "REV-6", 6),
    ],
)
def test_supported_terminal_numeric_revisions_are_normalized(
    filename: str,
    family: str,
    raw: str,
    normalized: str,
    order: int,
) -> None:
    result = parse_document_revision(filename)

    assert result.status is RevisionParseStatus.PARSED
    assert result.original_filename == filename
    assert result.family_key == family
    assert result.raw_revision == raw
    assert result.normalized_revision == normalized
    assert result.revision_order == order
    assert result.reason is None


def test_family_separators_are_normalized_without_fuzzy_matching() -> None:
    left = parse_document_revision("Fire-Safety_Plan.Rev 2.pdf")
    right = parse_document_revision("Fire Safety Plan Rev 2.pdf")
    unrelated = parse_document_revision("Fire Safety Report Rev 2.pdf")

    assert left.family_key == right.family_key == "fire safety plan"
    assert unrelated.family_key == "fire safety report"
    assert unrelated.family_key != left.family_key


def test_revision_comparison_uses_integer_semantics() -> None:
    assert compare_revision_orders(10, 4) == 1
    assert compare_revision_orders(4, 10) == -1
    assert compare_revision_orders(4, 4) == 0


@pytest.mark.parametrize(
    "filename",
    [
        "Structural Plan Rev A.pdf",
        "Structural Plan P01.pdf",
        "Structural Plan FINAL.pdf",
        "Structural Plan FINAL2.pdf",
        "Structural Plan IFC.pdf",
        "Structural Plan ISSUED.pdf",
        "Structural Plan FOR CONSTRUCTION.pdf",
        "Structural Plan LATEST.pdf",
        "Structural Plan Rev 3A.pdf",
        "Structural Plan Rev 3.1.pdf",
    ],
)
def test_unsupported_revision_labels_are_not_ordered(filename: str) -> None:
    result = parse_document_revision(filename)

    assert result.status is RevisionParseStatus.UNSUPPORTED
    assert result.reason is RevisionParseReason.UNSUPPORTED_REVISION_LABEL
    assert result.revision_order is None


def test_revision_looking_text_not_at_end_is_not_parsed() -> None:
    result = parse_document_revision("Structural Rev 2 drawing.pdf")

    assert result.status is RevisionParseStatus.NO_REVISION
    assert result.reason is RevisionParseReason.NO_REVISION_LABEL


def test_revision_requires_a_nonblank_family() -> None:
    result = parse_document_revision("Rev_04.pdf")

    assert result.status is RevisionParseStatus.UNSUPPORTED
    assert result.reason is RevisionParseReason.BLANK_DOCUMENT_FAMILY


def test_filename_without_revision_has_explicit_result() -> None:
    result = parse_document_revision("Structural Plan.pdf")

    assert result.status is RevisionParseStatus.NO_REVISION
    assert result.reason is RevisionParseReason.NO_REVISION_LABEL


def test_only_the_final_extension_is_removed() -> None:
    result = parse_document_revision("Structural Plan Rev 2.source.pdf")

    assert result.status is RevisionParseStatus.NO_REVISION
    assert result.filename_stem == "Structural Plan Rev 2.source"


def test_parsing_is_deterministic() -> None:
    filename = "Structural_Plan-Rev_04.pdf"

    assert parse_document_revision(filename) == parse_document_revision(filename)


def test_revision_integer_bound_is_documented_and_enforced() -> None:
    maximum = parse_document_revision(f"Structural Plan Rev {MAX_REVISION_ORDER}.pdf")
    too_large = parse_document_revision(f"Structural Plan Rev {MAX_REVISION_ORDER + 1}.pdf")

    assert maximum.status is RevisionParseStatus.PARSED
    assert maximum.revision_order == MAX_REVISION_ORDER
    assert too_large.status is RevisionParseStatus.UNSUPPORTED
    assert too_large.reason is RevisionParseReason.REVISION_OUT_OF_RANGE
    with pytest.raises(ValueError, match="revision order must be between"):
        compare_revision_orders(MAX_REVISION_ORDER + 1, 1)


def test_revision_policy_vocabulary_is_stable() -> None:
    assert DOCUMENT_REVISION_POLICY_VERSION == "document-revision/1"
    assert DocumentRevisionRule.FIRST_REVISION_CURRENT.value.startswith("DREV-")
    assert set(RevisionOutcome) == {
        RevisionOutcome.CURRENT,
        RevisionOutcome.HISTORICAL,
        RevisionOutcome.DUPLICATE,
        RevisionOutcome.REVIEW_REQUIRED,
    }
