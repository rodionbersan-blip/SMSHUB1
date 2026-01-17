from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ChatMessage:
    id: str
    deal_id: str
    sender_id: int
    text: str | None
    file_path: str | None
    file_name: str | None
    created_at: datetime
    system: bool = False

    def to_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "id": self.id,
            "deal_id": self.deal_id,
            "sender_id": self.sender_id,
            "text": self.text,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "created_at": self.created_at.isoformat(),
            "system": self.system,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | int | bool | None]) -> "ChatMessage":
        return cls(
            id=str(data["id"]),
            deal_id=str(data["deal_id"]),
            sender_id=int(data["sender_id"]),
            text=data.get("text"),
            file_path=data.get("file_path"),
            file_name=data.get("file_name"),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            system=bool(data.get("system", False)),
        )
