from __future__ import annotations

import hashlib
import imaplib
import re
from datetime import datetime
from email import message_from_bytes
from email.message import EmailMessage, Message
from email.policy import default
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Iterable

from .config import AppConfig, keyword_match
from .models import EmailRecord


WEAK_BODY_KEYWORDS = {
    "application",
    "applied",
    "job",
    "jobs",
    "position",
    "role",
    "recruiter",
    "recruiting",
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._chunks.append(data.strip())

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._chunks)).strip()


class ImapEmailClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def fetch_since(self, since: datetime, limit: int | None = None) -> list[EmailRecord]:
        self.config.validate_email_settings()
        since_token = since.strftime("%d-%b-%Y")
        fetch_limit = limit if limit is not None else self.config.max_emails
        records: list[EmailRecord] = []

        with imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port) as mailbox:
            mailbox.login(self.config.imap_username, self.config.imap_password)
            mailbox.select(self.config.imap_mailbox, readonly=True)

            status, data = mailbox.search(None, "SINCE", since_token)
            if status != "OK" or not data:
                return []

            message_ids = data[0].split()
            if fetch_limit > 0:
                message_ids = message_ids[-fetch_limit:]

            for message_num in message_ids:
                status, fetched = mailbox.fetch(message_num, "(RFC822)")
                if status != "OK" or not fetched:
                    continue

                raw_bytes = _first_message_bytes(fetched)
                if not raw_bytes:
                    continue

                records.append(email_record_from_bytes(raw_bytes))

        records.sort(key=lambda item: item.date)
        return records


def filter_relevant_emails(
    emails: Iterable[EmailRecord],
    keywords: list[str],
    exclude_keywords: list[str] | None = None,
) -> list[EmailRecord]:
    return [
        email
        for email in emails
        if is_relevant_email(email, keywords, exclude_keywords or [])
    ]


def is_relevant_email(email: EmailRecord, keywords: list[str], exclude_keywords: list[str]) -> bool:
    subject_from = f"{email.subject}\n{email.from_address}"
    body_excerpt = email.body[:2500]

    if _looks_like_job_alert(subject_from, exclude_keywords):
        return False
    if keyword_match([subject_from], keywords):
        return True

    body_keywords = [keyword for keyword in keywords if keyword not in WEAK_BODY_KEYWORDS]
    return keyword_match([body_excerpt], body_keywords)


def _looks_like_job_alert(subject_from: str, exclude_keywords: list[str]) -> bool:
    lowered = subject_from.lower()
    return any(keyword in lowered for keyword in exclude_keywords)


def email_record_from_bytes(raw_bytes: bytes) -> EmailRecord:
    parsed = message_from_bytes(raw_bytes, policy=default)
    subject = str(parsed.get("Subject", ""))
    from_address = str(parsed.get("From", ""))
    message_id = str(parsed.get("Message-ID", "")).strip()
    if not message_id:
        digest = hashlib.sha256(raw_bytes).hexdigest()[:24]
        message_id = f"generated-{digest}"

    parsed_date = _parse_email_date(str(parsed.get("Date", "")))
    body = extract_body(parsed)

    return EmailRecord(
        message_id=message_id,
        subject=subject,
        from_address=from_address,
        date=parsed_date,
        body=body,
    )


def email_record_from_text(text: str, subject: str = "Local text sample") -> EmailRecord:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    return EmailRecord(
        message_id=f"local-{digest}",
        subject=subject,
        from_address="local-file",
        date=datetime.now().astimezone(),
        body=text,
    )


def extract_body(message: Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if isinstance(message, EmailMessage):
        walkable = message.walk() if message.is_multipart() else [message]
    else:
        walkable = message.walk() if message.is_multipart() else [message]

    for part in walkable:
        content_disposition = str(part.get("Content-Disposition", "")).lower()
        if "attachment" in content_disposition:
            continue

        content_type = part.get_content_type()
        payload = _safe_payload(part)
        if not payload:
            continue

        if content_type == "text/plain":
            plain_parts.append(payload)
        elif content_type == "text/html":
            html_parts.append(_html_to_text(payload))

    body = "\n\n".join(plain_parts).strip()
    if body:
        return body
    return "\n\n".join(html_parts).strip()


def _safe_payload(part: Message) -> str:
    try:
        if hasattr(part, "get_content"):
            content = part.get_content()
            return content if isinstance(content, str) else ""
    except Exception:
        pass

    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.text()


def _parse_email_date(value: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(value)
        if parsed is not None:
            return parsed.astimezone()
    except (TypeError, ValueError, OverflowError):
        pass
    return datetime.now().astimezone()


def _first_message_bytes(fetched: list[bytes | tuple[bytes, bytes]]) -> bytes:
    for item in fetched:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return b""
