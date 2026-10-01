import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ReplyBody:
    latest: str
    quoted_text_start: int | None = None


_BOUNDARY_PATTERNS = (
    re.compile(r"(?im)^On .+ wrote:\s*$"),
    re.compile(r"(?im)^-{2,}\s*(?:Begin )?Forwarded message\s*-{2,}\s*$"),
    re.compile(r"(?im)^_{5,}\s*$"),
)


def select_latest_reply(body: str) -> ReplyBody:
    matches = [match for pattern in _BOUNDARY_PATTERNS if (match := pattern.search(body))]
    if not matches:
        return ReplyBody(latest=body)

    boundary = min(matches, key=lambda match: match.start())
    latest = body[: boundary.start()].rstrip()
    if not latest:
        return ReplyBody(latest=body)
    return ReplyBody(latest=latest, quoted_text_start=boundary.start())
