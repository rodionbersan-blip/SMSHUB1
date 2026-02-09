from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict

from cachebot.models.topup import Topup
from cachebot.storage import StateRepository


class TopupService:
    def __init__(self, repository: StateRepository) -> None:
        self._repository = repository
        self._lock = asyncio.Lock()
        snapshot = repository.snapshot()
        self._topups: Dict[str, Topup] = {item.invoice_id: item for item in snapshot.topups}

    async def create(self, *, user_id: int, amount: Decimal, invoice_id: str) -> Topup:
        if amount <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        async with self._lock:
            topup = Topup(
                invoice_id=invoice_id,
                user_id=user_id,
                amount=amount,
                created_at=datetime.now(timezone.utc),
            )
            self._topups[topup.invoice_id] = topup
            await self._persist_locked()
            return topup

    async def pop_paid(self, invoice_id: str) -> Topup | None:
        async with self._lock:
            topup = self._topups.pop(str(invoice_id), None)
            if topup:
                await self._persist_locked()
            return topup

    async def list_for_user(self, user_id: int) -> list[Topup]:
        async with self._lock:
            return [item for item in self._topups.values() if item.user_id == user_id]

    async def _persist_locked(self) -> None:
        await self._repository.persist_topups(list(self._topups.values()))
