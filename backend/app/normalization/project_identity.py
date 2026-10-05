import re
import unicodedata
from collections.abc import Callable, Mapping

IdentifierValueNormalizer = Callable[[str], str]


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def _required(value: str, *, field: str) -> str:
    normalized = _normalized_text(value)
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    return normalized


def normalize_project_code(value: str) -> str:
    return _required(value, field="project code").casefold()


def canonicalize_project_code(value: str) -> str:
    return _required(value, field="project code").upper()


def normalize_project_name(value: str) -> str:
    return _required(value, field="project name").casefold()


def normalize_identifier_type(value: str) -> str:
    return _required(value, field="identifier type").casefold()


def normalize_identifier(
    identifier_type: str,
    display_value: str,
    *,
    type_normalizers: Mapping[str, IdentifierValueNormalizer] | None = None,
) -> str:
    normalized_type = normalize_identifier_type(identifier_type)
    value = _required(display_value, field="identifier value")
    normalizer = (type_normalizers or {}).get(normalized_type)
    normalized_value = normalizer(value) if normalizer else value.casefold()
    return _required(normalized_value, field="normalized identifier value")
