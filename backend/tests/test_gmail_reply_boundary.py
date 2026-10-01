import pytest

from app.adapters.gmail.reply_boundary import select_latest_reply


def test_selects_text_before_gmail_reply_boundary() -> None:
    body = "Latest answer.\n\nOn Tue, Sep 30, 2026 at 10:00 AM Sender wrote:\n> Earlier"

    result = select_latest_reply(body)

    assert result.latest == "Latest answer."
    assert result.quoted_text_start == body.index("On Tue")


@pytest.mark.parametrize(
    "boundary",
    ["---------- Forwarded message ---------", "----- Begin Forwarded message -----"],
)
def test_selects_text_before_forwarded_message(boundary: str) -> None:
    body = f"Please review.\n\n{boundary}\nFrom: sender@example.com"

    result = select_latest_reply(body)

    assert result.latest == "Please review."
    assert result.quoted_text_start == body.index(boundary)


def test_preserves_ambiguous_or_boundary_only_text() -> None:
    ambiguous = "The phrase On Tuesday wrote: belongs in this sentence."
    boundary_only = "On Tue, Sep 30, 2026 Sender wrote:\nEarlier"

    assert select_latest_reply(ambiguous).latest == ambiguous
    assert select_latest_reply(boundary_only).latest == boundary_only
