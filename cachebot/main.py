from __future__ import annotations

import asyncio
import contextlib
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from cachebot.config import Config
from cachebot.deps import AppDeps, get_deps, wire
from cachebot.handlers import commands, deal_flow, p2p
from cachebot.services.adverts import AdvertService
from cachebot.services.crypto_pay import CryptoPayClient
from cachebot.services.deals import DealService
from cachebot.services.kb_client import KBClient
from cachebot.services.disputes import DisputeService
from cachebot.services.rate_provider import RateProvider
from cachebot.services.reviews import ReviewService
from cachebot.services.scheduler import dispute_timer_watcher, expiry_watcher, invoice_watcher
from cachebot.services.topups import TopupService
from cachebot.services.users import UserService
from cachebot.services.chats import ChatService
from cachebot.storage import StateRepository
from cachebot.webhook import create_app


async def run_bot() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
    config = Config.from_env()
    logging.info("Using state file: %s", config.storage_path)
    logging.info("Commands file: %s", commands.__file__)
    repository = StateRepository(config.storage_path)
    rate_provider = RateProvider(
        repository,
        default_rate=config.default_usd_rate,
        default_fee_percent=config.fee_percent,
        default_withdraw_fee_percent=config.withdraw_fee_percent,
    )
    config.withdraw_fee_percent = await rate_provider.withdraw_fee_percent()
    crypto_pay = CryptoPayClient(config.crypto_pay_token)
    kb_client = KBClient(config.kb_api_url, config.kb_api_token)
    user_service = UserService(repository)
    review_service = ReviewService(repository)
    dispute_service = DisputeService(repository)
    advert_service = AdvertService(repository)
    topup_service = TopupService(repository)
    chat_service = ChatService(repository)
    deal_service = DealService(
        repository,
        rate_provider,
        config.payment_window_minutes,
        config.offer_window_minutes,
        admin_ids=config.admin_ids,
    )

    wire(
        AppDeps(
            config=config,
            deal_service=deal_service,
            rate_provider=rate_provider,
            crypto_pay=crypto_pay,
            kb_client=kb_client,
            user_service=user_service,
            review_service=review_service,
            dispute_service=dispute_service,
            advert_service=advert_service,
            topup_service=topup_service,
            chat_service=chat_service,
        )
    )

    bot = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()
    dp.include_router(commands.router)
    dp.include_router(deal_flow.router)
    dp.include_router(p2p.router)

    expiry_task = asyncio.create_task(expiry_watcher(deal_service, advert_service, bot))
    invoice_task = asyncio.create_task(
        invoice_watcher(
            deal_service,
            crypto_pay,
            kb_client,
            bot,
            config.invoice_poll_interval,
        )
    )
    dispute_task = asyncio.create_task(dispute_timer_watcher(deal_service, bot))

    app = create_app(bot, get_deps())
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        config.webhook_host,
        config.webhook_port,
    )
    await site.start()
    logging.info(
        "Crypto Pay webhook listening on http://%s:%s%s",
        config.webhook_host,
        config.webhook_port,
        config.webhook_path,
    )

    try:
        await dp.start_polling(bot)
    finally:
        for task in (expiry_task, invoice_task, dispute_task):
            task.cancel()
        await asyncio.gather(expiry_task, invoice_task, dispute_task, return_exceptions=True)
        with contextlib.suppress(Exception):
            await runner.cleanup()
        await crypto_pay.close()
        await bot.session.close()


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
