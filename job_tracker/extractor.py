from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import date, datetime
from email.utils import parseaddr
from typing import Any

from .config import AppConfig, keyword_match
from .models import ApplicationUpdate, EmailRecord, clean_cell, normalize_status


class JobUpdateExtractor:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.rules = RuleBasedExtractor(config.email_keywords)
        self.ollama = OllamaExtractor(config) if config.use_ollama else None

    def extract(self, email: EmailRecord) -> list[ApplicationUpdate]:
        if self.ollama is None:
            return self.rules.extract(email)

        try:
            return self.ollama.extract(email)
        except OllamaUnavailableError as error:
            print(f"Ollama unavailable, using rule-based extraction for this email: {error}")
            return self.rules.extract(email)
        except ValueError as error:
            print(f"Ollama returned invalid JSON, using rule-based extraction for this email: {error}")
            return self.rules.extract(email)


class OllamaUnavailableError(RuntimeError):
    pass


class OllamaExtractor:
    def __init__(self, config: AppConfig) -> None:
        self.base_url = config.ollama_base_url.rstrip("/")
        self.model = config.ollama_model
        self.timeout = config.ollama_timeout_seconds

    def extract(self, email: EmailRecord) -> list[ApplicationUpdate]:
        prompt = _build_prompt(email)
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract structured job application updates from emails. "
                        "Return only valid JSON. Do not invent facts that are not in the email."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }

        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as error:
            raise OllamaUnavailableError(str(error)) from error

        data = json.loads(raw)
        content = data.get("message", {}).get("content", "")
        if not content:
            raise ValueError("missing message.content")

        parsed = json.loads(content)
        return _updates_from_model_json(parsed, email)


class RuleBasedExtractor:
    def __init__(self, keywords: list[str]) -> None:
        self.keywords = keywords

    def extract(self, email: EmailRecord) -> list[ApplicationUpdate]:
        text = f"{email.subject}\n{email.from_address}\n{email.body}"
        if not keyword_match([text], self.keywords):
            return []

        status = self._status(text)
        if status == "unknown":
            return []

        company = self._company(email)
        role = self._role(text)
        return [
            ApplicationUpdate(
                company=company,
                role=role,
                status=status,
                event_date=email.date.date(),
                confidence=0.55,
                notes=self._notes(status),
                source_message_id=email.message_id,
                source_subject=email.subject,
                source_from=email.from_address,
                source_date=email.date,
            )
        ]

    def _status(self, text: str) -> str:
        lowered = text.lower()
        checks = [
            (
                "rejected",
                [
                    "unfortunately",
                    "not move forward",
                    "not moving forward",
                    "pursue other candidates",
                    "other candidates",
                    "no longer under consideration",
                    "will not be proceeding",
                ],
            ),
            (
                "offer",
                [
                    "offer letter",
                    "extend an offer",
                    "pleased to offer",
                    "congratulations",
                ],
            ),
            (
                "interview",
                [
                    "interview",
                    "phone screen",
                    "onsite",
                    "schedule a call",
                    "speak with you",
                    "meet with",
                ],
            ),
            (
                "assessment",
                [
                    "assessment",
                    "coding challenge",
                    "take-home",
                    "take home",
                    "hackerrank",
                    "technical exercise",
                ],
            ),
            (
                "received",
                [
                    "received your application",
                    "thank you for applying",
                    "thanks for applying",
                    "application has been received",
                ],
            ),
            (
                "applied",
                [
                    "your application",
                    "application for",
                    "applied to",
                ],
            ),
            (
                "follow_up",
                [
                    "next steps",
                    "following up",
                    "quick update",
                ],
            ),
        ]

        for status, phrases in checks:
            if any(phrase in lowered for phrase in phrases):
                return status
        return "unknown"

    def _company(self, email: EmailRecord) -> str:
        text = f"{email.subject}\n{email.body}"
        patterns = [
            r"thank you for applying to\s+([A-Z][A-Za-z0-9&.,' -]{2,60})",
            r"thanks for applying to\s+([A-Z][A-Za-z0-9&.,' -]{2,60})",
            r"application (?:to|with|at)\s+([A-Z][A-Za-z0-9&.,' -]{2,60})",
            r"update from\s+([A-Z][A-Za-z0-9&.,' -]{2,60})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return _clean_company(match.group(1))

        display_name, address = parseaddr(email.from_address)
        candidate = display_name or address.split("@")[0]
        candidate = re.sub(r"\b(careers?|jobs?|recruiting|recruiter|talent|no.?reply|notifications?)\b", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"[@._-]+", " ", candidate)
        return clean_cell(candidate.title(), "Unknown Company")

    def _role(self, text: str) -> str:
        patterns = [
            r"(?:for|regarding)\s+(?!applying\b)(?:your\s+)?(?:the\s+)?([A-Za-z][A-Za-z0-9 /,&.+#'-]{2,80}?)\s+(?:position|role|job|opening|application)",
            r"(?:position|role)\s+(?:of|as)\s+([A-Za-z][A-Za-z0-9 /,&.+#'-]{2,80}?)(?:[.,\n]|$)",
            r"application for\s+(?:the\s+)?([A-Za-z][A-Za-z0-9 /,&.+#'-]{2,80}?)(?:\s+at|\s+with|[.,\n]|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return _clean_role(match.group(1))
        return "Unknown Role"

    def _notes(self, status: str) -> str:
        notes = {
            "received": "Application receipt detected by local rules.",
            "applied": "Application mention detected by local rules.",
            "assessment": "Assessment or coding exercise detected by local rules.",
            "interview": "Interview or scheduling language detected by local rules.",
            "offer": "Offer language detected by local rules.",
            "rejected": "Rejection language detected by local rules.",
            "follow_up": "Follow-up language detected by local rules.",
        }
        return notes.get(status, "Detected by local rules.")


def _build_prompt(email: EmailRecord) -> str:
    body = email.body[:8000]
    return f"""
Analyze this email and decide whether it contains a job application update.

Allowed status values:
- applied: the user submitted an application
- received: the company confirms receiving the application
- assessment: coding challenge, assessment, technical exercise, or test
- interview: any interview, recruiter call, phone screen, onsite, or scheduling step
- offer: offer or compensation step
- rejected: rejection or no longer under consideration
- withdrawn: the user withdrew or the application was closed by request
- follow_up: meaningful update or next-step message that does not fit the above
- unknown: job related, but status cannot be inferred

Return JSON with this exact shape:
{{
  "is_job_related": true,
  "updates": [
    {{
      "company": "Company name or null",
      "role": "Role title or null",
      "status": "one allowed status",
      "event_date": "YYYY-MM-DD or null",
      "confidence": 0.0,
      "notes": "short reason"
    }}
  ]
}}

If it is not related to a job application, return:
{{"is_job_related": false, "updates": []}}

Email metadata:
Subject: {email.subject}
From: {email.from_address}
Date: {email.date.date().isoformat()}

Email body:
{body}
""".strip()


def _updates_from_model_json(parsed: Any, email: EmailRecord) -> list[ApplicationUpdate]:
    if isinstance(parsed, list):
        parsed = {"is_job_related": True, "updates": parsed}
    if not isinstance(parsed, dict):
        raise ValueError("model response is not an object")
    if parsed.get("is_job_related") is False:
        return []

    raw_updates = parsed.get("updates", [])
    if not isinstance(raw_updates, list):
        raise ValueError("updates is not a list")

    updates: list[ApplicationUpdate] = []
    for index, raw in enumerate(raw_updates):
        if not isinstance(raw, dict):
            continue
        status = normalize_status(raw.get("status"))
        if status == "unknown":
            continue
        updates.append(
            ApplicationUpdate(
                company=raw.get("company") or "Unknown Company",
                role=raw.get("role") or "Unknown Role",
                status=status,
                event_date=_parse_model_date(raw.get("event_date")),
                confidence=raw.get("confidence", 0.7),
                notes=raw.get("notes") or "Extracted by local Ollama model.",
                source_message_id=email.message_id,
                source_subject=email.subject,
                source_from=email.from_address,
                source_date=email.date,
                event_index=index,
            )
        )
    return updates


def _parse_model_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        value = value.strip()
        match = re.search(r"\d{4}-\d{2}-\d{2}", value)
        if match:
            return date.fromisoformat(match.group(0))
    return None


def _clean_company(value: str) -> str:
    value = re.split(r"[\n.!?]", value, maxsplit=1)[0]
    value = re.sub(r"\s+(for|about|regarding|to)\s+.*$", "", value, flags=re.IGNORECASE)
    return clean_cell(value.strip(" -:,."))


def _clean_role(value: str) -> str:
    value = re.split(r"[\n.!?]", value, maxsplit=1)[0]
    value = re.sub(r"\s+(at|with|for)\s+.*$", "", value, flags=re.IGNORECASE)
    return clean_cell(value.strip(" -:,."))
