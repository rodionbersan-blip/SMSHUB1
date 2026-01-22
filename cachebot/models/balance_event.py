from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict


@dataclass(slots=True)
class BalanceEvent:
    id: str
    user_id: int
    amount: Decimal
    kind: str
    created_at: datetime
    meta: Dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "amount": str(self.amount),
            "kind": self.kind,
            "created_at": self.created_at.isoformat(),
            "meta": self.meta or {},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BalanceEvent":
        return cls(
            id=str(data.get("id")),
            user_id=int(data.get("user_id")),
            amount=Decimal(str(data.get("amount"))),
            kind=str(data.get("kind") or ""),
            created_at=datetime.fromisoformat(data.get("created_at")),
            meta=data.get("meta") or {},
        )
