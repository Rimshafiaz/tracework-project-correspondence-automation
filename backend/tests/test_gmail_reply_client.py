from base64 import urlsafe_b64decode
from email import message_from_bytes
from json import loads
from types import SimpleNamespace
from uuid import uuid4

import pytest
from google.auth.credentials import AnonymousCredentials
from googleapiclient.discovery import build
from googleapiclient.http import HttpRequest

from app.adapters.gmail.reply_client import (
    GMAIL_REPLY_METADATA_HEADERS,
    GmailReplyMetadataError,
    build_gmail_reply,
    deterministic_rfc_message_id,
    fetch_live_source_metadata,
    parse_live_source_metadata,
    search_sent_by_rfc_message_id,
    send_gmail_reply,
)


def _response(**overrides):
    response = {
        "id": "source-message",
        "threadId": "source-thread",
        "payload": {
            "headers": [
                {"name": "Message-ID", "value": "<source@example.test>"},
                {"name": "References", "value": "<older@example.test> <source@example.test>"},
                {"name": "In-Reply-To", "value": "<older@example.test>"},
                {"name": "Subject", "value": "Re: Programme update"},
                {"name": "From", "value": "Client <client@example.test>"},
            ]
        },
    }
    response.update(overrides)
    return response


def test_live_source_metadata_requests_only_reply_headers_and_parses_them():
    request = SimpleNamespace(execute=lambda: _response())
    messages = SimpleNamespace(get=lambda **kwargs: (captured.update(kwargs), request)[1])
    service = SimpleNamespace(users=lambda: SimpleNamespace(messages=lambda: messages))
    captured = {}

    result = fetch_live_source_metadata(service, "source-message")

    assert captured == {
        "userId": "me",
        "id": "source-message",
        "format": "metadata",
        "metadataHeaders": list(GMAIL_REPLY_METADATA_HEADERS),
    }
    assert result.rfc_message_id == "<source@example.test>"
    assert result.thread_id == "source-thread"


def test_reply_construction_is_deterministic_and_preserves_threading_headers():
    attempt_id = uuid4()
    source = parse_live_source_metadata(_response())
    message_id = deterministic_rfc_message_id(attempt_id, "Tracework.Example.Test")

    reply = build_gmail_reply(
        sender_email="tracework@example.test",
        recipient_email="client@example.test",
        subject="Re: Programme update",
        body="Please confirm the outstanding date.\n",
        thread_id="source-thread",
        source=source,
        rfc_message_id=message_id,
    )

    parsed = message_from_bytes(urlsafe_b64decode(reply.raw + "=" * (-len(reply.raw) % 4)))
    assert reply.thread_id == "source-thread"
    assert parsed["Subject"] == "Re: Programme update"
    assert parsed["Message-ID"] == message_id
    assert parsed["In-Reply-To"] == "<source@example.test>"
    assert parsed["References"] == "<older@example.test> <source@example.test>"
    assert parsed.get_payload(decode=True).decode().replace("\r\n", "\n") == (
        "Please confirm the outstanding date.\n"
    )


def test_reply_construction_rejects_wrong_live_thread_or_missing_message_id():
    source = parse_live_source_metadata(_response())
    with pytest.raises(GmailReplyMetadataError, match="thread"):
        build_gmail_reply(
            sender_email="tracework@example.test",
            recipient_email="client@example.test",
            subject="Subject",
            body="Body",
            thread_id="other-thread",
            source=source,
            rfc_message_id="<outbound@example.test>",
        )
    response = _response()
    response["payload"]["headers"] = [
        header for header in response["payload"]["headers"] if header["name"] != "Message-ID"
    ]
    with pytest.raises(GmailReplyMetadataError, match="Message-ID"):
        parse_live_source_metadata(response)


def test_recovery_search_is_bounded_and_send_returns_validated_receipt():
    captured = {}
    search_request = SimpleNamespace(
        execute=lambda: {"messages": [{"id": "sent-1", "threadId": "thread-1"}]}
    )
    send_request = SimpleNamespace(execute=lambda: {"id": "sent-2", "threadId": "thread-1"})
    messages = SimpleNamespace(
        list=lambda **kwargs: (captured.update(kwargs), search_request)[1],
        send=lambda **kwargs: (captured.update({"send": kwargs}), send_request)[1],
    )
    service = SimpleNamespace(users=lambda: SimpleNamespace(messages=lambda: messages))

    recovery = search_sent_by_rfc_message_id(
        service, rfc_message_id="<reply@example.test>"
    )
    receipt = send_gmail_reply(
        service,
        SimpleNamespace(raw="raw-content", thread_id="thread-1"),
    )

    assert recovery.message_ids == ("sent-1",)
    assert captured["q"] == "in:sent rfc822msgid:reply@example.test"
    assert captured["maxResults"] == 3
    assert captured["send"] == {
        "userId": "me",
        "body": {"raw": "raw-content", "threadId": "thread-1"},
    }
    assert receipt.message_id == "sent-2"


def test_send_constructs_real_gmail_request_with_raw_and_thread_in_body(monkeypatch):
    service = build("gmail", "v1", credentials=AnonymousCredentials(), static_discovery=True)
    captured = {}

    def execute(request):
        captured["method"] = request.method
        captured["body"] = loads(request.body)
        return {"id": "sent-2", "threadId": "thread-1"}

    monkeypatch.setattr(HttpRequest, "execute", execute)
    receipt = send_gmail_reply(
        service,
        SimpleNamespace(raw="raw-content", thread_id="thread-1"),
    )

    assert captured == {
        "method": "POST",
        "body": {"raw": "raw-content", "threadId": "thread-1"},
    }
    assert receipt.message_id == "sent-2"


def test_recovery_search_treats_gmail_zero_result_response_as_empty():
    request = SimpleNamespace(execute=lambda: {"resultSizeEstimate": 0})
    messages = SimpleNamespace(list=lambda **_kwargs: request)
    service = SimpleNamespace(users=lambda: SimpleNamespace(messages=lambda: messages))

    result = search_sent_by_rfc_message_id(
        service,
        rfc_message_id="<reply@example.test>",
    )

    assert result.message_ids == ()
    assert result.thread_ids == ()


def test_recovery_search_rejects_explicit_malformed_messages():
    request = SimpleNamespace(execute=lambda: {"messages": {}})
    messages = SimpleNamespace(list=lambda **_kwargs: request)
    service = SimpleNamespace(users=lambda: SimpleNamespace(messages=lambda: messages))

    with pytest.raises(GmailReplyMetadataError, match="invalid messages"):
        search_sent_by_rfc_message_id(
            service,
            rfc_message_id="<reply@example.test>",
        )
