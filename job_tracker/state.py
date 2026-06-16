from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class TrackerState:
    last_sync_utc: datetime | None = None
    processed_message_ids: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> "TrackerState":
        if not path.exists():
            return cls()

        data = json.loads(path.read_text(encoding="utf-8"))
        raw_last_sync = data.get("last_sync_utc")
        last_sync = None
        if raw_last_sync:
            last_sync = datetime.fromisoformat(raw_last_sync.replace("Z", "+00:00"))

        return cls(
            last_sync_utc=last_sync,
            processed_message_ids=set(data.get("processed_message_ids", [])),
        )

    def mark_processed(self, message_id: str) -> None:
        if message_id:
            self.processed_message_ids.add(message_id)

    def is_processed(self, message_id: str) -> bool:
        return bool(message_id and message_id in self.processed_message_ids)

    def mark_synced_now(self) -> None:
        self.last_sync_utc = datetime.now(timezone.utc)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_sync_utc": self.last_sync_utc.isoformat().replace("+00:00", "Z")
            if self.last_sync_utc
            else None,
            "processed_message_ids": sorted(self.processed_message_ids),
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp_path.replace(path)
