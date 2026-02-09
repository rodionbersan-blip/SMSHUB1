from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass(slots=True)
class Topup:
    invoice_id: str
    user_id: int
    amount: Decimal
    created_at: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "invoice_id": self.invoice_id,
            "user_id": str(self.user_id),
            "amount": str(self.amount),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "Topup":
        created_raw = data.get("created_at")
        created_at = (
            datetime.fromisoformat(created_raw)
            if created_raw
            else datetime.now(timezone.utc)
        )
        return cls(
            invoice_id=str(data["invoice_id"]),
            user_id=int(data["user_id"]),
            amount=Decimal(data["amount"]),
            created_at=created_at,
        )
