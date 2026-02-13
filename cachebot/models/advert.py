from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class AdvertSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(slots=True)
class Advert:
    id: str
    owner_id: int
    side: AdvertSide
    price_rub: Decimal
    total_usdt: Decimal
    remaining_usdt: Decimal
    min_rub: Decimal
    max_rub: Decimal
    banks: list[str]
    terms: str | None
    active: bool
    is_merchant: bool
    created_at: datetime
    public_id: str

    @property
    def hashtag(self) -> str:
        return f"#{self.public_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "owner_id": self.owner_id,
            "side": self.side.value,
            "price_rub": str(self.price_rub),
            "total_usdt": str(self.total_usdt),
            "remaining_usdt": str(self.remaining_usdt),
            "min_rub": str(self.min_rub),
            "max_rub": str(self.max_rub),
            "banks": list(self.banks),
            "terms": self.terms,
            "active": self.active,
            "is_merchant": self.is_merchant,
            "created_at": self.created_at.isoformat(),
            "public_id": self.public_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Advert":
        return cls(
            id=data["id"],
            owner_id=int(data["owner_id"]),
            side=AdvertSide(data["side"]),
            price_rub=Decimal(data["price_rub"]),
            total_usdt=Decimal(data["total_usdt"]),
            remaining_usdt=Decimal(data.get("remaining_usdt") or data["total_usdt"]),
            min_rub=Decimal(data["min_rub"]),
            max_rub=Decimal(data["max_rub"]),
            banks=list(data.get("banks") or []),
            terms=data.get("terms"),
            active=bool(data.get("active", False)),
            is_merchant=bool(data.get("is_merchant", False)),
            created_at=datetime.fromisoformat(data["created_at"]),
            public_id=data.get("public_id") or _fallback_public_id(data["id"]),
        )


def _fallback_public_id(source_id: str) -> str:
    trimmed = source_id.replace("-", "")[:8]
    return f"O{trimmed.upper()}"
