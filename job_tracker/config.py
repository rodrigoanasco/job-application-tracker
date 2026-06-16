from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def split_csv(value: str) -> list[str]:
    return [part.strip().lower() for part in value.split(",") if part.strip()]


@dataclass(frozen=True)
class AppConfig:
    imap_host: str
    imap_port: int
    imap_username: str
    imap_password: str
    imap_mailbox: str
    lookback_days: int
    max_emails: int
    email_keywords: list[str]
    use_ollama: bool
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_seconds: int
    data_dir: Path
    output_excel: Path
    state_file: Path

    @classmethod
    def load(cls, env_path: str | Path = ".env") -> "AppConfig":
        load_env_file(Path(env_path))

        data_dir = Path(os.getenv("DATA_DIR", "data"))
        default_keywords = (
            "application,applied,interview,recruiter,recruiting,position,role,"
            "assessment,coding challenge,take-home,offer,unfortunately,next steps,"
            "thank you for applying"
        )

        return cls(
            imap_host=os.getenv("IMAP_HOST", ""),
            imap_port=env_int("IMAP_PORT", 993),
            imap_username=os.getenv("IMAP_USERNAME", ""),
            imap_password=os.getenv("IMAP_PASSWORD", ""),
            imap_mailbox=os.getenv("IMAP_MAILBOX", "INBOX"),
            lookback_days=env_int("LOOKBACK_DAYS", 45),
            max_emails=env_int("MAX_EMAILS", 200),
            email_keywords=split_csv(os.getenv("EMAIL_KEYWORDS", default_keywords)),
            use_ollama=env_bool("USE_OLLAMA", True),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
            ollama_timeout_seconds=env_int("OLLAMA_TIMEOUT_SECONDS", 45),
            data_dir=data_dir,
            output_excel=Path(os.getenv("OUTPUT_EXCEL", str(data_dir / "job_applications.xlsx"))),
            state_file=Path(os.getenv("STATE_FILE", str(data_dir / "state.json"))),
        )

    def validate_email_settings(self) -> None:
        missing = [
            name
            for name, value in {
                "IMAP_HOST": self.imap_host,
                "IMAP_USERNAME": self.imap_username,
                "IMAP_PASSWORD": self.imap_password,
            }.items()
            if not value
        ]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing email settings: {joined}. Copy .env.example to .env and fill them in.")


def keyword_match(text_parts: Iterable[str], keywords: list[str]) -> bool:
    haystack = "\n".join(part or "" for part in text_parts).lower()
    return any(keyword in haystack for keyword in keywords)
