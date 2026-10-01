from unittest.mock import MagicMock, call

import pytest
from googleapiclient.errors import HttpError

from app.adapters.gmail.history_sync import (
    GmailHistoryResyncRequired,
    collect_history_message_ids,
)


def test_history_sync_collects_eligible_ids_and_uses_final_page_cursor() -> None:
    service = MagicMock()
    list_history = service.users.return_value.history.return_value.list
    list_history.return_value.execute.side_effect = [
        {
            "history": [
                {
                    "messagesAdded": [
                        {"message": {"id": "message-1"}},
                        {"message": {"id": "message-2"}},
                    ],
                    "labelsAdded": [
                        {
                            "message": {"id": "message-3"},
                            "labelIds": ["Label_123"],
                        },
                        {
                            "message": {"id": "ignored-label"},
                            "labelIds": ["OTHER"],
                        },
                    ],
                    "labelsRemoved": [
                        {
                            "message": {"id": "ignored-removal"},
                            "labelIds": ["Label_123"],
                        }
                    ],
                }
            ],
            "nextPageToken": "next-page",
            "historyId": "intermediate-cursor",
        },
        {
            "history": [
                {
                    "messagesAdded": [
                        {"message": {"id": "message-2"}},
                        {"message": {"id": "message-4"}},
                    ]
                }
            ],
            "historyId": "final-cursor",
        },
    ]

    result = collect_history_message_ids(
        service,
        start_history_id="100",
        label_id="Label_123",
    )

    assert result.message_ids == (
        "message-1",
        "message-2",
        "message-3",
        "message-4",
    )
    assert result.final_history_id == "final-cursor"
    assert list_history.call_args_list == [
        call(
            userId="me",
            startHistoryId="100",
            labelId="Label_123",
            historyTypes=["messageAdded", "labelAdded"],
            maxResults=500,
        ),
        call(
            userId="me",
            startHistoryId="100",
            labelId="Label_123",
            historyTypes=["messageAdded", "labelAdded"],
            maxResults=500,
            pageToken="next-page",
        ),
    ]


def test_history_sync_advances_cursor_when_there_are_no_changes() -> None:
    service = MagicMock()
    service.users.return_value.history.return_value.list.return_value.execute.return_value = {
        "historyId": "101"
    }

    result = collect_history_message_ids(
        service,
        start_history_id="100",
        label_id="Label_123",
    )

    assert result.message_ids == ()
    assert result.final_history_id == "101"


def test_expired_history_cursor_signals_bounded_resync() -> None:
    service = MagicMock()
    response = MagicMock(status=404, reason="Not Found")
    service.users.return_value.history.return_value.list.return_value.execute.side_effect = HttpError(
        response,
        b"{}",
    )

    with pytest.raises(GmailHistoryResyncRequired) as raised:
        collect_history_message_ids(
            service,
            start_history_id="expired",
            label_id="Label_123",
        )

    assert raised.value.start_history_id == "expired"


def test_non_cursor_api_errors_are_not_hidden() -> None:
    service = MagicMock()
    response = MagicMock(status=500, reason="Server Error")
    error = HttpError(response, b"{}")
    service.users.return_value.history.return_value.list.return_value.execute.side_effect = error

    with pytest.raises(HttpError) as raised:
        collect_history_message_ids(
            service,
            start_history_id="100",
            label_id="Label_123",
        )

    assert raised.value is error


@pytest.mark.parametrize(
    ("start_history_id", "label_id", "message"),
    [(" ", "Label_123", "start_history_id"), ("100", " ", "label_id")],
)
def test_history_sync_rejects_invalid_scope(
    start_history_id: str,
    label_id: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        collect_history_message_ids(
            MagicMock(),
            start_history_id=start_history_id,
            label_id=label_id,
        )
