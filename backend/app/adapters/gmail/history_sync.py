from dataclasses import dataclass
from typing import Any

from googleapiclient.errors import HttpError


class GmailHistoryResyncRequired(Exception):
    def __init__(self, start_history_id: str) -> None:
        self.start_history_id = start_history_id
        super().__init__(f"Gmail history cursor {start_history_id!r} requires resync")


@dataclass(frozen=True)
class GmailHistorySyncResult:
    message_ids: tuple[str, ...]
    final_history_id: str


def collect_history_message_ids(
    service: Any,
    *,
    start_history_id: str,
    label_id: str,
) -> GmailHistorySyncResult:
    start_history_id = start_history_id.strip()
    label_id = label_id.strip()
    if not start_history_id:
        raise ValueError("start_history_id must not be blank")
    if not label_id:
        raise ValueError("label_id must not be blank")

    message_ids: dict[str, None] = {}
    page_token = None
    final_history_id = None
    while True:
        request = {
            "userId": "me",
            "startHistoryId": start_history_id,
            "labelId": label_id,
            "historyTypes": ["messageAdded", "labelAdded"],
            "maxResults": 500,
        }
        if page_token:
            request["pageToken"] = page_token

        try:
            page = service.users().history().list(**request).execute()
        except HttpError as error:
            if error.resp.status == 404:
                raise GmailHistoryResyncRequired(start_history_id) from error
            raise

        for history in page.get("history", ()):
            _collect_eligible_ids(history, label_id, message_ids)

        page_token = page.get("nextPageToken")
        if not page_token:
            final_history_id = page.get("historyId")
            break

    if not final_history_id:
        raise ValueError("Final Gmail history page did not include historyId")
    return GmailHistorySyncResult(
        message_ids=tuple(message_ids),
        final_history_id=str(final_history_id),
    )


def _collect_eligible_ids(
    history: dict[str, Any],
    label_id: str,
    message_ids: dict[str, None],
) -> None:
    for added in history.get("messagesAdded", ()):
        message_id = _message_id(added)
        if message_id:
            message_ids.setdefault(message_id, None)

    for labeled in history.get("labelsAdded", ()):
        if label_id not in labeled.get("labelIds", ()):
            continue
        message_id = _message_id(labeled)
        if message_id:
            message_ids.setdefault(message_id, None)


def _message_id(change: dict[str, Any]) -> str | None:
    message = change.get("message")
    if not isinstance(message, dict):
        return None
    message_id = str(message.get("id", "")).strip()
    return message_id or None
