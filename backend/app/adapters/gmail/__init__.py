from app.adapters.gmail.attachment_content import (
    AttachmentContentError,
    AttachmentContentFailure,
    download_gmail_attachment,
)
from app.adapters.gmail.client import (
    GMAIL_READONLY_SCOPE,
    GMAIL_SCOPES,
    GMAIL_SEND_SCOPE,
    authorize_gmail,
    create_gmail_client,
)
from app.adapters.gmail.history_sync import (
    GmailHistoryResyncRequired,
    GmailHistorySyncResult,
    collect_history_message_ids,
)
from app.adapters.gmail.initial_sync import GmailInitialSyncResult, collect_initial_message_ids
from app.adapters.gmail.message_parser import fetch_gmail_message, parse_gmail_message
from app.adapters.gmail.normalizer import GmailAttachment, GmailMessage, normalize_gmail_message
from app.adapters.gmail.reply_client import (
    GMAIL_REPLY_METADATA_HEADERS,
    GmailLiveSourceMetadata,
    GmailReplyMessage,
    GmailReplyMetadataError,
    GmailRecoverySearch,
    GmailSendReceipt,
    build_gmail_reply,
    deterministic_rfc_message_id,
    fetch_live_source_metadata,
    normalize_reply_subject,
    parse_live_source_metadata,
    search_sent_by_rfc_message_id,
    send_gmail_reply,
)

__all__ = [
    "AttachmentContentError",
    "AttachmentContentFailure",
    "GMAIL_SCOPES",
    "GMAIL_READONLY_SCOPE",
    "GMAIL_SEND_SCOPE",
    "GMAIL_REPLY_METADATA_HEADERS",
    "GmailAttachment",
    "GmailHistoryResyncRequired",
    "GmailHistorySyncResult",
    "GmailInitialSyncResult",
    "GmailMessage",
    "GmailLiveSourceMetadata",
    "GmailReplyMessage",
    "GmailReplyMetadataError",
    "GmailRecoverySearch",
    "GmailSendReceipt",
    "authorize_gmail",
    "collect_initial_message_ids",
    "collect_history_message_ids",
    "create_gmail_client",
    "download_gmail_attachment",
    "fetch_gmail_message",
    "fetch_live_source_metadata",
    "parse_live_source_metadata",
    "build_gmail_reply",
    "deterministic_rfc_message_id",
    "normalize_reply_subject",
    "search_sent_by_rfc_message_id",
    "send_gmail_reply",
    "normalize_gmail_message",
    "parse_gmail_message",
]
