from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GmailInitialSyncResult:
    message_ids: tuple[str, ...]
    starting_history_id: str


def collect_initial_message_ids(
    service: Any,
    *,
    label_id: str,
    after_epoch_seconds: int,
) -> GmailInitialSyncResult:
    label_id = label_id.strip()
    if not label_id:
        raise ValueError("label_id must not be blank")
    if after_epoch_seconds < 0:
        raise ValueError("after_epoch_seconds must be nonnegative")

    users = service.users()
    profile = users.getProfile(userId="me").execute()
    starting_history_id = profile.get("historyId")
    if not starting_history_id:
        raise ValueError("Gmail profile response did not include historyId")

    message_ids: dict[str, None] = {}
    page_token = None
    while True:
        request = {
            "userId": "me",
            "labelIds": [label_id],
            "q": f"after:{after_epoch_seconds}",
            "maxResults": 500,
        }
        if page_token:
            request["pageToken"] = page_token

        page = users.messages().list(**request).execute()
        for message in page.get("messages", ()):
            message_id = message.get("id")
            if message_id:
                message_ids.setdefault(message_id, None)

        page_token = page.get("nextPageToken")
        if not page_token:
            break

    return GmailInitialSyncResult(
        message_ids=tuple(message_ids),
        starting_history_id=str(starting_history_id),
    )
