from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List


@dataclass(slots=True)
class MessageItem:
    author_id: int
    text: str
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "author_id": self.author_id,
            "text": self.text,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MessageItem":
        return cls(
            author_id=int(data["author_id"]),
            text=str(data["text"]),
            created_at=datetime.fromisoformat(data["created_at"]),
        )


@dataclass(slots=True)
class EvidenceItem:
    kind: str
    file_id: str
    author_id: int

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "file_id": self.file_id, "author_id": self.author_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceItem":
        return cls(
            kind=str(data["kind"]),
            file_id=str(data["file_id"]),
            author_id=int(data.get("author_id", 0)),
        )


@dataclass(slots=True)
class Dispute:
    id: str
    deal_id: str
    opened_by: int
    opened_at: datetime
    reason: str
    comment: str | None
    evidence: List[EvidenceItem] = field(default_factory=list)
    messages: List[MessageItem] = field(default_factory=list)
    resolved: bool = False
    resolved_at: datetime | None = None
    resolved_by: int | None = None
    seller_amount: str | None = None
    buyer_amount: str | None = None
    assigned_to: int | None = None
    assigned_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "deal_id": self.deal_id,
            "opened_by": self.opened_by,
            "opened_at": self.opened_at.isoformat(),
            "reason": self.reason,
            "comment": self.comment,
            "evidence": [item.to_dict() for item in self.evidence],
            "messages": [item.to_dict() for item in self.messages],
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "seller_amount": self.seller_amount,
            "buyer_amount": self.buyer_amount,
            "assigned_to": self.assigned_to,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Dispute":
        return cls(
            id=data["id"],
            deal_id=data["deal_id"],
            opened_by=int(data["opened_by"]),
            opened_at=datetime.fromisoformat(data["opened_at"]),
            reason=data.get("reason") or "",
            comment=data.get("comment"),
            evidence=[EvidenceItem.from_dict(item) for item in data.get("evidence", [])],
            messages=[MessageItem.from_dict(item) for item in data.get("messages", [])],
            resolved=bool(data.get("resolved")),
            resolved_at=(
                datetime.fromisoformat(data["resolved_at"])
                if data.get("resolved_at")
                else None
            ),
            resolved_by=data.get("resolved_by"),
            seller_amount=data.get("seller_amount"),
            buyer_amount=data.get("buyer_amount"),
            assigned_to=data.get("assigned_to"),
            assigned_at=(
                datetime.fromisoformat(data["assigned_at"])
                if data.get("assigned_at")
                else None
            ),
        )
