from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class DealStatus(str, Enum):
    OPEN = "open"
    PENDING = "pending"
    RESERVED = "reserved"
    PAID = "paid"
    DISPUTE = "dispute"
    COMPLETED = "completed"
    CANCELED = "canceled"
    EXPIRED = "expired"


class QrStage(str, Enum):
    IDLE = "idle"
    AWAITING_SELLER_BANK = "awaiting_seller_bank"
    AWAITING_SELLER_ATTACH = "awaiting_seller_attach"
    AWAITING_BUYER_READY = "awaiting_buyer_ready"
    AWAITING_SELLER_PHOTO = "awaiting_seller_photo"
    READY = "ready"


@dataclass(slots=True)
class Deal:
    id: str
    seller_id: int
    usd_amount: Decimal
    rate: Decimal
    fee_percent: Decimal
    fee_amount: Decimal
    usdt_amount: Decimal
    created_at: datetime
    expires_at: datetime
    status: DealStatus = DealStatus.OPEN
    buyer_id: int | None = None
    offer_initiator_id: int | None = None
    offer_expires_at: datetime | None = None
    invoice_id: str | None = None
    invoice_url: str | None = None
    comment: str | None = None
    public_id: str = ""
    atm_bank: str | None = None
    qr_stage: QrStage = QrStage.IDLE
    qr_bank_options: list[str] = field(default_factory=list)
    qr_photo_id: str | None = None
    buyer_cash_confirmed: bool = False
    seller_cash_confirmed: bool = False
    payout_completed: bool = False
    dispute_available_at: datetime | None = None
    dispute_notified: bool = False
    dispute_opened_by: int | None = None
    dispute_opened_at: datetime | None = None
    is_p2p: bool = False
    advert_id: str | None = None
    balance_reserved: bool = False

    @property
    def hashtag(self) -> str:
        return f"#{self.public_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "seller_id": self.seller_id,
            "usd_amount": str(self.usd_amount),
            "rate": str(self.rate),
            "fee_percent": str(self.fee_percent),
            "fee_amount": str(self.fee_amount),
            "usdt_amount": str(self.usdt_amount),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "status": self.status.value,
            "buyer_id": self.buyer_id,
            "offer_initiator_id": self.offer_initiator_id,
            "offer_expires_at": self.offer_expires_at.isoformat()
            if self.offer_expires_at
            else None,
            "invoice_id": self.invoice_id,
            "invoice_url": self.invoice_url,
            "comment": self.comment,
            "public_id": self.public_id,
            "atm_bank": self.atm_bank,
            "qr_stage": self.qr_stage.value,
            "qr_bank_options": self.qr_bank_options,
            "qr_photo_id": self.qr_photo_id,
            "buyer_cash_confirmed": self.buyer_cash_confirmed,
            "seller_cash_confirmed": self.seller_cash_confirmed,
            "payout_completed": self.payout_completed,
            "dispute_available_at": self.dispute_available_at.isoformat()
            if self.dispute_available_at
            else None,
            "dispute_notified": self.dispute_notified,
            "dispute_opened_by": self.dispute_opened_by,
            "dispute_opened_at": self.dispute_opened_at.isoformat()
            if self.dispute_opened_at
            else None,
            "is_p2p": self.is_p2p,
            "advert_id": self.advert_id,
            "balance_reserved": self.balance_reserved,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Deal":
        return cls(
            id=data["id"],
            seller_id=int(data["seller_id"]),
            usd_amount=Decimal(data["usd_amount"]),
            rate=Decimal(data["rate"]),
            fee_percent=Decimal(data["fee_percent"]),
            fee_amount=Decimal(data["fee_amount"]),
            usdt_amount=Decimal(data["usdt_amount"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            status=DealStatus(data["status"]),
            buyer_id=data.get("buyer_id"),
            offer_initiator_id=data.get("offer_initiator_id"),
            offer_expires_at=(
                datetime.fromisoformat(data["offer_expires_at"])
                if data.get("offer_expires_at")
                else None
            ),
            invoice_id=data.get("invoice_id"),
            invoice_url=data.get("invoice_url"),
            comment=data.get("comment"),
            public_id=data.get("public_id") or _fallback_public_id(data["id"]),
            atm_bank=data.get("atm_bank"),
            qr_stage=QrStage(data.get("qr_stage") or QrStage.IDLE.value),
            qr_bank_options=list(data.get("qr_bank_options") or []),
            qr_photo_id=data.get("qr_photo_id"),
            buyer_cash_confirmed=bool(data.get("buyer_cash_confirmed")),
            seller_cash_confirmed=bool(data.get("seller_cash_confirmed")),
            payout_completed=bool(data.get("payout_completed")),
            dispute_available_at=(
                datetime.fromisoformat(data["dispute_available_at"])
                if data.get("dispute_available_at")
                else None
            ),
            dispute_notified=bool(data.get("dispute_notified")),
            dispute_opened_by=data.get("dispute_opened_by"),
            dispute_opened_at=(
                datetime.fromisoformat(data["dispute_opened_at"])
                if data.get("dispute_opened_at")
                else None
            ),
            is_p2p=bool(data.get("is_p2p")),
            advert_id=data.get("advert_id"),
            balance_reserved=bool(data.get("balance_reserved", True)),
        )


def _fallback_public_id(source_id: str) -> str:
    trimmed = source_id.replace("-", "")[:8]
    return f"D{trimmed.upper()}"
