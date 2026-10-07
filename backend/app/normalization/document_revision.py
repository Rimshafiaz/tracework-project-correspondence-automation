import re
import unicodedata

from app.contracts.document_revision import (
    MAX_REVISION_ORDER,
    DocumentRevisionParseResult,
    RevisionParseReason,
    RevisionParseStatus,
)


_NUMERIC_REVISION_SUFFIX = re.compile(
    r"^(?P<family>.*?)(?P<boundary>[\s._-]+)"
    r"(?P<revision>(?:revision|rev|r)[\s._-]*(?P<number>\d+))$",
    re.IGNORECASE,
)
_NUMERIC_REVISION_TOKEN = re.compile(
    r"^(?:revision|rev|r)[\s._-]*(?P<number>\d+)$",
    re.IGNORECASE,
)
_REVISION_WITHOUT_FAMILY = re.compile(
    r"^(?:revision|rev|r)[\s._-]*\d+$",
    re.IGNORECASE,
)
_UNSUPPORTED_REVISION_SUFFIX = re.compile(
    r"(?:^|[\s._-]+)(?:"
    r"(?:revision|rev|r)[\s._-]*(?:[a-z]+|\d+[a-z]+|\d+\.\d+)"
    r"|p\d+"
    r"|final\d*"
    r"|issued"
    r"|ifc"
    r"|for[\s._-]+construction"
    r"|latest"
    r")$",
    re.IGNORECASE,
)
_FAMILY_SEPARATORS = re.compile(r"[\s._-]+")


def parse_document_revision(filename: str) -> DocumentRevisionParseResult:
    """Parse a supported terminal numeric revision without guessing.

    V1 accepts revision orders from 0 through ``MAX_REVISION_ORDER`` so the
    value remains representable by a PostgreSQL INTEGER in the later schema.
    Only the final filename extension is removed before suffix recognition.
    """

    original_stem = _remove_final_extension(filename)
    filename_stem = unicodedata.normalize("NFKC", original_stem)
    match = _match_numeric_revision(original_stem)
    if match is not None:
        raw_family, raw_revision, revision_digits = match
        family_key = normalize_document_family(raw_family)
        if not family_key:
            return _not_parsed(
                filename,
                filename_stem,
                RevisionParseStatus.UNSUPPORTED,
                RevisionParseReason.BLANK_DOCUMENT_FAMILY,
            )
        revision_order = int(unicodedata.normalize("NFKC", revision_digits))
        if revision_order > MAX_REVISION_ORDER:
            return _not_parsed(
                filename,
                filename_stem,
                RevisionParseStatus.UNSUPPORTED,
                RevisionParseReason.REVISION_OUT_OF_RANGE,
            )
        return DocumentRevisionParseResult(
            original_filename=filename,
            filename_stem=filename_stem,
            status=RevisionParseStatus.PARSED,
            family_key=family_key,
            raw_revision=raw_revision,
            normalized_revision=f"REV-{revision_order}",
            revision_order=revision_order,
        )

    if _REVISION_WITHOUT_FAMILY.fullmatch(filename_stem):
        return _not_parsed(
            filename,
            filename_stem,
            RevisionParseStatus.UNSUPPORTED,
            RevisionParseReason.BLANK_DOCUMENT_FAMILY,
        )
    if _UNSUPPORTED_REVISION_SUFFIX.search(filename_stem):
        return _not_parsed(
            filename,
            filename_stem,
            RevisionParseStatus.UNSUPPORTED,
            RevisionParseReason.UNSUPPORTED_REVISION_LABEL,
        )
    return _not_parsed(
        filename,
        filename_stem,
        RevisionParseStatus.NO_REVISION,
        RevisionParseReason.NO_REVISION_LABEL,
    )


def normalize_document_family(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _FAMILY_SEPARATORS.sub(" ", normalized).strip()


def compare_revision_orders(left: int, right: int) -> int:
    """Return -1, 0, or 1 using numeric revision semantics."""

    _validate_revision_order(left)
    _validate_revision_order(right)
    return (left > right) - (left < right)


def _remove_final_extension(filename: str) -> str:
    final_separator = max(filename.rfind("/"), filename.rfind("\\"))
    final_dot = filename.rfind(".")
    if final_dot > final_separator + 0:
        return filename[:final_dot]
    return filename


def _match_numeric_revision(filename_stem: str) -> tuple[str, str, str] | None:
    direct_match = _NUMERIC_REVISION_SUFFIX.fullmatch(filename_stem)
    if direct_match is not None:
        return (
            direct_match.group("family"),
            direct_match.group("revision"),
            direct_match.group("number"),
        )

    # NFKC may normalize full-width separators or revision characters. Test
    # suffixes independently so the returned raw label still comes from the
    # original filename rather than reconstructed normalized text.
    for boundary_index, character in enumerate(filename_stem):
        if unicodedata.normalize("NFKC", character) not in " ._-":
            continue
        revision_index = boundary_index
        while revision_index < len(filename_stem) and (
            unicodedata.normalize("NFKC", filename_stem[revision_index])
            in " ._-"
        ):
            revision_index += 1
        raw_revision = filename_stem[revision_index:]
        revision_match = _NUMERIC_REVISION_TOKEN.fullmatch(
            unicodedata.normalize("NFKC", raw_revision)
        )
        if revision_match is not None:
            return (
                filename_stem[:boundary_index],
                raw_revision,
                revision_match.group("number"),
            )
    return None


def _validate_revision_order(value: int) -> None:
    if isinstance(value, bool) or not 0 <= value <= MAX_REVISION_ORDER:
        raise ValueError(
            f"revision order must be between 0 and {MAX_REVISION_ORDER}"
        )


def _not_parsed(
    original_filename: str,
    filename_stem: str,
    status: RevisionParseStatus,
    reason: RevisionParseReason,
) -> DocumentRevisionParseResult:
    return DocumentRevisionParseResult(
        original_filename=original_filename,
        filename_stem=filename_stem,
        status=status,
        reason=reason,
    )
