from app.normalization.correspondence import normalize_body, normalize_email, normalize_source
from app.normalization.project_identity import normalize_identifier, normalize_identifier_type, normalize_project_code, normalize_project_name

__all__ = [
    "normalize_body",
    "normalize_email",
    "normalize_identifier",
    "normalize_identifier_type",
    "normalize_project_code",
    "normalize_project_name",
    "normalize_source",
]
