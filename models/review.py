from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Review:
    deal_id: str
    from_user_id: int
    to_user_id: int
    rating: int
    comment: str | None
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "deal_id": self.deal_id,
            "from_user_id": self.from_user_id,
            "to_user_id": self.to_user_id,
            "rating": self.rating,
            "comment": self.comment,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Review":
        return cls(
            deal_id=data["deal_id"],
            from_user_id=int(data["from_user_id"]),
            to_user_id=int(data["to_user_id"]),
            rating=int(data["rating"]),
            comment=data.get("comment"),
            created_at=datetime.fromisoformat(data["created_at"]),
        )
