from __future__ import annotations

import asyncio
from decimal import Decimal

from cachebot.models.rate import RateSnapshot
from cachebot.storage import RateSettings, StateRepository


class RateProvider:
    def __init__(
        self,
        repository: StateRepository,
        *,
        default_rate: Decimal,
        default_fee_percent: Decimal,
        default_withdraw_fee_percent: Decimal,
        default_transfer_fee_percent: Decimal,
    ) -> None:
        self._repository = repository
        state = repository.snapshot()
        settings = state.settings or RateSettings(
            default_rate,
            default_fee_percent,
            default_fee_percent,
            default_withdraw_fee_percent,
            default_transfer_fee_percent,
        )
        self._snapshot = RateSnapshot(
            settings.usd_rate,
            settings.fee_percent,
            settings.buyer_fee_percent,
        )
        self._withdraw_fee_percent = settings.withdraw_fee_percent
        self._transfer_fee_percent = settings.transfer_fee_percent
        self._lock = asyncio.Lock()

    async def set_rate(self, usd_rate: Decimal | None = None, fee_percent: Decimal | None = None) -> RateSnapshot:
        async with self._lock:
            rate = usd_rate if usd_rate is not None else self._snapshot.usd_rate
            fee = fee_percent if fee_percent is not None else self._snapshot.fee_percent
            buyer_fee = (
                self._snapshot.buyer_fee_percent
                if hasattr(self._snapshot, "buyer_fee_percent")
                else fee
            )
            self._snapshot = RateSnapshot(rate, fee, buyer_fee)
            await self._repository.persist_settings(
                RateSettings(rate, fee, buyer_fee, self._withdraw_fee_percent, self._transfer_fee_percent)
            )
            return self._snapshot

    async def snapshot(self) -> RateSnapshot:
        async with self._lock:
            return RateSnapshot(
                self._snapshot.usd_rate,
                self._snapshot.fee_percent,
                self._snapshot.buyer_fee_percent,
            )

    async def withdraw_fee_percent(self) -> Decimal:
        async with self._lock:
            return self._withdraw_fee_percent

    async def set_withdraw_fee_percent(self, value: Decimal) -> Decimal:
        async with self._lock:
            self._withdraw_fee_percent = value
            await self._repository.persist_settings(
                RateSettings(
                    self._snapshot.usd_rate,
                    self._snapshot.fee_percent,
                    self._snapshot.buyer_fee_percent,
                    value,
                    self._transfer_fee_percent,
                )
            )
            return self._withdraw_fee_percent

    async def transfer_fee_percent(self) -> Decimal:
        async with self._lock:
            return self._transfer_fee_percent

    async def set_transfer_fee_percent(self, value: Decimal) -> Decimal:
        async with self._lock:
            self._transfer_fee_percent = value
            await self._repository.persist_settings(
                RateSettings(
                    self._snapshot.usd_rate,
                    self._snapshot.fee_percent,
                    self._snapshot.buyer_fee_percent,
                    self._withdraw_fee_percent,
                    value,
                )
            )
            return self._transfer_fee_percent

    async def buyer_fee_percent(self) -> Decimal:
        async with self._lock:
            return self._snapshot.buyer_fee_percent

    async def set_buyer_fee_percent(self, value: Decimal) -> Decimal:
        async with self._lock:
            self._snapshot = RateSnapshot(
                self._snapshot.usd_rate,
                self._snapshot.fee_percent,
                value,
            )
            await self._repository.persist_settings(
                RateSettings(
                    self._snapshot.usd_rate,
                    self._snapshot.fee_percent,
                    value,
                    self._withdraw_fee_percent,
                    self._transfer_fee_percent,
                )
            )
            return value
