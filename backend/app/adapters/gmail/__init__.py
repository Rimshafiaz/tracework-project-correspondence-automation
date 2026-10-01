from app.adapters.gmail.attachment_content import (
    AttachmentContentError,
    AttachmentContentFailure,
    download_gmail_attachment,
)
from app.adapters.gmail.client import GMAIL_SCOPES, authorize_gmail, create_gmail_client
from app.adapters.gmail.history_sync import (
    GmailHistoryResyncRequired,
    GmailHistorySyncResult,
    collect_history_message_ids,
)
from app.adapters.gmail.initial_sync import GmailInitialSyncResult, collect_initial_message_ids
from app.adapters.gmail.message_parser import fetch_gmail_message, parse_gmail_message
from app.adapters.gmail.normalizer import GmailAttachment, GmailMessage, normalize_gmail_message

__all__ = [
    "AttachmentContentError",
    "AttachmentContentFailure",
    "GMAIL_SCOPES",
    "GmailAttachment",
    "GmailHistoryResyncRequired",
    "GmailHistorySyncResult",
    "GmailInitialSyncResult",
    "GmailMessage",
    "authorize_gmail",
    "collect_initial_message_ids",
    "collect_history_message_ids",
    "create_gmail_client",
    "download_gmail_attachment",
    "fetch_gmail_message",
    "normalize_gmail_message",
    "parse_gmail_message",
]
