from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


ALLOWED_STATUSES = {
    "applied",
    "received",
    "assessment",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
    "follow_up",
    "unknown",
}


def clean_cell(value: Optional[str], fallback: str = "") -> str:
    if value is None:
        return fallback
    compact = re.sub(r"\s+", " ", str(value)).strip()
    return compact or fallback


def normalize_status(value: Optional[str]) -> str:
    status = clean_cell(value, "unknown").lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "application_received": "received",
        "phone_screen": "interview",
        "onsite": "interview",
        "technical_interview": "interview",
        "coding_challenge": "assessment",
        "take_home": "assessment",
        "next_steps": "follow_up",
        "followup": "follow_up",
        "declined": "rejected",
        "rejection": "rejected",
    }
    status = aliases.get(status, status)
    return status if status in ALLOWED_STATUSES else "unknown"


def normalize_key_part(value: str) -> str:
    value = clean_cell(value, "unknown").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip() or "unknown"


@dataclass(frozen=True)
class EmailRecord:
    message_id: str
    subject: str
    from_address: str
    date: datetime
    body: str


@dataclass
class ApplicationUpdate:
    company: str
    role: str
    status: str
    event_date: Optional[date]
    confidence: float
    notes: str
    source_message_id: str
    source_subject: str
    source_from: str
    source_date: datetime
    event_index: int = 0

    def __post_init__(self) -> None:
        self.company = clean_cell(self.company, "Unknown Company")
        self.role = clean_cell(self.role, "Unknown Role")
        self.status = normalize_status(self.status)
        self.notes = clean_cell(self.notes)
        self.source_message_id = clean_cell(self.source_message_id)
        self.source_subject = clean_cell(self.source_subject)
        self.source_from = clean_cell(self.source_from)
        try:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))
        except (TypeError, ValueError):
            self.confidence = 0.0

    @property
    def application_key(self) -> str:
        return f"{normalize_key_part(self.company)}::{normalize_key_part(self.role)}"

    @property
    def event_id(self) -> str:
        base = self.source_message_id or f"{self.source_from}|{self.source_subject}|{self.source_date.isoformat()}"
        return f"{base}#{self.event_index}"
