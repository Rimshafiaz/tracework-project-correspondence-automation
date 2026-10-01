from unittest.mock import MagicMock, call

import pytest

from app.adapters.gmail.initial_sync import collect_initial_message_ids


def test_initial_sync_uses_epoch_label_pagination_and_deduplication() -> None:
    service = MagicMock()
    users = service.users.return_value
    users.getProfile.return_value.execute.return_value = {"historyId": "9001"}
    list_messages = users.messages.return_value.list
    list_messages.return_value.execute.side_effect = [
        {
            "messages": [{"id": "message-1"}, {"id": "message-2"}],
            "nextPageToken": "next-page",
        },
        {"messages": [{"id": "message-2"}, {"id": "message-3"}]},
    ]

    result = collect_initial_message_ids(
        service,
        label_id="Label_123",
        after_epoch_seconds=1790838000,
    )

    assert result.message_ids == ("message-1", "message-2", "message-3")
    assert result.starting_history_id == "9001"
    users.getProfile.assert_called_once_with(userId="me")
    assert list_messages.call_args_list == [
        call(
            userId="me",
            labelIds=["Label_123"],
            q="after:1790838000",
            maxResults=500,
        ),
        call(
            userId="me",
            labelIds=["Label_123"],
            q="after:1790838000",
            maxResults=500,
            pageToken="next-page",
        ),
    ]


def test_initial_sync_accepts_an_empty_mailbox() -> None:
    service = MagicMock()
    users = service.users.return_value
    users.getProfile.return_value.execute.return_value = {"historyId": "42"}
    users.messages.return_value.list.return_value.execute.return_value = {}

    result = collect_initial_message_ids(
        service,
        label_id="Label_123",
        after_epoch_seconds=0,
    )

    assert result.message_ids == ()
    assert result.starting_history_id == "42"


@pytest.mark.parametrize(
    ("label_id", "after_epoch_seconds", "message"),
    [(" ", 0, "label_id"), ("Label_123", -1, "after_epoch_seconds")],
)
def test_initial_sync_rejects_invalid_scope(
    label_id: str,
    after_epoch_seconds: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        collect_initial_message_ids(
            MagicMock(),
            label_id=label_id,
            after_epoch_seconds=after_epoch_seconds,
        )
