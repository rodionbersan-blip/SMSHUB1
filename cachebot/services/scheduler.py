from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

from cachebot.models.deal import Deal, DealStatus
from cachebot.services.crypto_pay import CryptoPayClient
from cachebot.services.deals import DealService
from cachebot.services.adverts import AdvertService
from cachebot.services.kb_client import KBClient
from cachebot.services.support import SupportService

logger = logging.getLogger(__name__)


async def expiry_watcher(
    deal_service: DealService,
    advert_service: AdvertService,
    bot: Bot,
    interval: int = 30,
) -> None:
    while True:
        try:
            expired = await deal_service.cleanup_expired()
            for deal in expired:
                if deal.is_p2p and deal.advert_id:
                    try:
                        base_usdt = deal.usd_amount / deal.rate
                        await advert_service.restore_volume(deal.advert_id, base_usdt)
                    except Exception:
                        pass
                text = f"⏳ Предложение {deal.hashtag} не было принято вовремя и отменено."
                await bot.send_message(deal.seller_id, text)
                if deal.buyer_id:
                    await bot.send_message(deal.buyer_id, text)
        except Exception as exc:  # pragma: no cover - protection loop
            logger.exception("Expiry watcher error: %s", exc)
        await asyncio.sleep(interval)


async def dispute_timer_watcher(deal_service: DealService, bot: Bot, interval: int = 30) -> None:
    while True:
        try:
            ready = await deal_service.list_dispute_ready()
            for deal in ready:
                text = (
                    f"⏳ Таймер по сделке {deal.hashtag} истёк.\n"
                    "Если есть спорные моменты, советуем открыть спор."
                )
                await bot.send_message(deal.seller_id, text)
                if deal.buyer_id:
                    await bot.send_message(deal.buyer_id, text)
                await deal_service.mark_dispute_notified(deal.id)
        except Exception as exc:  # pragma: no cover
            logger.exception("Dispute timer watcher error: %s", exc)
        await asyncio.sleep(interval)


async def invoice_watcher(
    deal_service: DealService,
    crypto_client: CryptoPayClient,
    kb_client: KBClient,
    bot: Bot,
    interval: int,
) -> None:
    while True:
        try:
            deals = await deal_service.reserved_deals_with_invoices()
            invoices = await crypto_client.fetch_invoices([deal.invoice_id for deal in deals])
            paid_ids = {invoice.invoice_id for invoice in invoices if invoice.status == "paid"}
            for invoice_id in paid_ids:
                deal = await deal_service.mark_invoice_paid(invoice_id)
                await handle_paid_invoice(deal, kb_client, bot)
        except Exception as exc:  # pragma: no cover
            logger.exception("Invoice watcher error: %s", exc)
    await asyncio.sleep(interval)


async def support_inactive_watcher(
    support_service: SupportService,
    bot: Bot,
    interval: int = 300,
) -> None:
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            cutoff_iso = cutoff.isoformat()
            inactive = await support_service.list_inactive_tickets(cutoff_iso)
            for ticket in inactive:
                try:
                    await bot.send_message(
                        ticket.user_id,
                        "🕓 Чат поддержки закрыт автоматически из-за отсутствия активности 24 часа.",
                    )
                except Exception:
                    pass
                await support_service.close(ticket.id)
        except Exception as exc:  # pragma: no cover
            logger.exception("Support inactive watcher error: %s", exc)
        await asyncio.sleep(interval)


async def handle_paid_invoice(deal: Deal, kb_client: KBClient, bot: Bot) -> None:
    builder = InlineKeyboardBuilder()
    builder.button(text="К сделке", callback_data=f"deal_info:{deal.id}")
    await bot.send_message(
        deal.seller_id,
        "✅ Платеж отправлен!\n"
        "Ожидай выбора банка для снятия.",
        reply_markup=builder.as_markup(),
    )
    if deal.buyer_id:
        await bot.send_message(
            deal.buyer_id,
            f"✅ Платеж по сделке {deal.hashtag} подтвержден.\n"
            "Выбери банк и запроси QR в меню сделки.",
            reply_markup=builder.as_markup(),
        )
