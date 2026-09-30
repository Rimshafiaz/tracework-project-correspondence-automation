def normalize_source(value: str) -> str:
    return value.strip().casefold()


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def normalize_body(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")
