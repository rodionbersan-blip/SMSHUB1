from __future__ import annotations

from contextlib import suppress
import logging
from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from typing import List
from uuid import uuid4

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder

from cachebot.constants import (
    PROFILE_VIEW_PREFIX,
    BANK_OPTIONS,
    bank_label,
    QR_REQUEST_PREFIX,
    QR_BANK_SELECT_PREFIX,
    QR_SELLER_BANK_PREFIX,
    QR_SELLER_READY_PREFIX,
    QR_SELLER_ATTACH_PREFIX,
    QR_BUYER_READY_PREFIX,
    QR_VIEW_PREFIX,
    QR_BUYER_DONE_PREFIX,
    QR_SELLER_DONE_PREFIX,
)
from cachebot.deps import get_deps
from cachebot.keyboards import MenuAction, MenuButtons, base_keyboard, inline_menu
from cachebot.models.deal import Deal, DealStatus, QrStage
from cachebot.models.dispute import EvidenceItem
from cachebot.models.review import Review
from cachebot.models.user import ApplicationStatus, MerchantApplication, UserProfile, UserRole
from cachebot.services.users import MerchantRecord

router = Router(name="commands")
ROLE_SELLER = "role:seller"
ROLE_MERCHANT = "role:merchant"
APP_VIEW_PREFIX = "app:view:"
APP_ACCEPT_PREFIX = "app:accept:"
APP_REJECT_PREFIX = "app:reject:"
MY_DEALS_PAGE_PREFIX = "mydeals:page:"
MY_DEALS_VIEW_PREFIX = "mydeals:view:"
DEAL_CANCEL_PREFIX = "dealact:cancel:"
DEAL_CANCEL_CONFIRM_PREFIX = "dealact:cancel:confirm:"
DEAL_COMPLETE_PREFIX = "dealact:complete:"
MESSAGE_DEAL_PREFIX = "deal_message:"
DEAL_INFO_PREFIX = "deal_info:"
REVIEW_START_PREFIX = "review:start:"
REVIEW_RATE_PREFIX = "review:rate:"
REVIEW_SKIP_PREFIX = "review:skip:"
REVIEWS_VIEW_PREFIX = "reviews:view:"
REVIEWS_BACK_PREFIX = "reviews:back:"
DISPUTE_OPEN_PREFIX = "dispute:open:"
DISPUTE_REASON_PREFIX = "dispute:reason:"
DISPUTE_EVIDENCE_PREFIX = "dispute:evidence:"
DISPUTE_APPEND_PREFIX = "dispute:append:"
DISPUTE_LIST_PREFIX = "dispute:list:"
DISPUTE_VIEW_PREFIX = "dispute:view:"
DISPUTE_EVIDENCE_VIEW_PREFIX = "dispute:evidence:view:"
DISPUTE_CLOSE_PREFIX = "dispute:close:"
DISPUTE_CLOSE_SIDE_PREFIX = "dispute:close:side:"
DISPUTE_CLOSE_BUYER_PREFIX = "dispute:close:buyer:"
DISPUTE_CLOSE_SELLER_PREFIX = "dispute:close:seller:"
DISPUTE_CLOSE_CONFIRM_PREFIX = "dispute:close:confirm:"
DISPUTE_PAYOUT_PREFIX = "dispute:payout:"
DISPUTE_TAKE_PREFIX = "dispute:take:"
QR_SELLER_CONFIRM_STEP1_PREFIX = "qr_seller_confirm1:"
QR_SELLER_CONFIRM_STEP2_PREFIX = "qr_seller_confirm2:"
DEALS_PER_PAGE = 7
ADMIN_DEALS_PER_PAGE = 10
BALANCE_WITHDRAW = "balance:withdraw"
ADMIN_PANEL_MENU = "admin:panel"
ADMIN_PANEL_MERCHANTS = "admin:panel:merchants"
ADMIN_PANEL_APPS = "admin:panel:apps"
ADMIN_PANEL_RATES = "admin:panel:rates"
ADMIN_MERCHANT_VIEW_PREFIX = "admin:merchant:view:"
ADMIN_MERCHANT_DEALS_PREFIX = "admin:merchant:deals:"
ADMIN_MERCHANT_DEALS_PAGE_PREFIX = "admin:merchant:deals:page:"
ADMIN_MERCHANT_DEAL_VIEW_PREFIX = "admin:merchant:deal:view:"
ADMIN_MERCHANT_EXCLUDE_PREFIX = "admin:merchant:exclude:"
ADMIN_RATE_SET = "admin:rate:set"
ADMIN_FEE_SET = "admin:fee:set"
ADMIN_FEE_KIND_WITHDRAW = "admin:fee:withdraw"
ADMIN_FEE_KIND_DEAL = "admin:fee:deal"
ADMIN_PANEL_MODERATORS = "admin:panel:moderators"
ADMIN_MODERATOR_ADD = "admin:moderator:add"
ADMIN_MODERATOR_VIEW_PREFIX = "admin:moderator:view:"
ADMIN_MODERATOR_REMOVE_PREFIX = "admin:moderator:remove:"
ADMIN_MODERATOR_DISPUTES_PREFIX = "admin:moderator:disputes:"
STATUS_TITLES = {
    DealStatus.OPEN: "Ожидает покупателя",
    DealStatus.RESERVED: "Ожидаем оплату",
    DealStatus.PAID: "Оплата получена",
    DealStatus.COMPLETED: "Завершена",
    DealStatus.CANCELED: "Отменена",
    DealStatus.EXPIRED: "Истекла",
}
STATUS_SHORT = {
    DealStatus.OPEN: "Открыта",
    DealStatus.RESERVED: "В работе",
    DealStatus.PAID: "Оплачено",
    DealStatus.COMPLETED: "Закрыта",
    DealStatus.CANCELED: "Отменена",
    DealStatus.EXPIRED: "Истекла",
}
STATUS_BUTTON_LABELS = {
    DealStatus.OPEN: "🟡 Не оплачено",
    DealStatus.RESERVED: "🟡 Не оплачено",
    DealStatus.PAID: "💰 Оплачено",
    DealStatus.COMPLETED: "✅ Успешно",
    DealStatus.CANCELED: "⛔ Отменена",
    DealStatus.EXPIRED: "⏳ Истекла",
}


class MerchantApplicationState(StatesGroup):
    choosing_banks = State()
    personal_bank = State()
    risk_ack = State()
    waiting_photos = State()


class AdminRateState(StatesGroup):
    waiting_rate = State()
    waiting_fee = State()


class WithdrawState(StatesGroup):
    waiting_amount = State()


class QrRequestState(StatesGroup):
    selecting_banks = State()


class SellerQrUploadState(StatesGroup):
    waiting_photo = State()


class ReviewState(StatesGroup):
    waiting_comment = State()


class DisputeState(StatesGroup):
    waiting_reason_text = State()
    waiting_evidence = State()
    waiting_append_text = State()
    waiting_append_evidence = State()


class DisputeAdminState(StatesGroup):
    choose_side = State()
    buyer_full = State()
    buyer_amount = State()
    seller_full = State()
    seller_amount = State()
    confirm = State()


class ModeratorAdminState(StatesGroup):
    waiting_username = State()


def _command_args(message: Message) -> str:
    if not message.text:
        return ""
    parts = message.text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


async def _has_dispute_access(user_id: int, deps) -> bool:
    if user_id in deps.config.admin_ids:
        return True
    return await deps.user_service.is_moderator(user_id)


def _format_decimal(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.001"))
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _role_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="💸 Продажа USDT", callback_data=ROLE_SELLER)
    builder.button(text="👔 Стать мерчантом", callback_data=ROLE_MERCHANT)
    builder.adjust(2)
    return builder


def _bank_keyboard(selected: List[str]) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for key, label in BANK_OPTIONS.items():
        prefix = "✅ " if key in selected else ""
        builder.button(text=f"{prefix}{label}", callback_data=f"bank:{key}")
    builder.button(text="Готово", callback_data="bank:done")
    builder.adjust(3, 1)
    return builder


def _qr_bank_keyboard(selected: List[str], allowed: List[str] | None = None) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for key, label in BANK_OPTIONS.items():
        if allowed is not None and key not in allowed:
            continue
        prefix = "✅ " if key in selected else ""
        builder.button(text=f"{prefix}{label}", callback_data=f"{QR_BANK_SELECT_PREFIX}{key}")
    builder.button(text="Готово", callback_data=f"{QR_BANK_SELECT_PREFIX}done")
    builder.button(text="Отмена", callback_data=f"{QR_BANK_SELECT_PREFIX}cancel")
    builder.adjust(3, 1, 1)
    return builder


def _yes_no_keyboard(prefix: str) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да", callback_data=f"{prefix}:yes")
    builder.button(text="Нет", callback_data=f"{prefix}:no")
    builder.adjust(2)
    return builder


async def _start_merchant_application(
    callback: CallbackQuery, state: FSMContext, deps=None
) -> bool:
    user = callback.from_user
    if not user:
        return False
    deps = deps or get_deps()
    if await deps.user_service.has_merchant_access(user.id):
        await deps.user_service.set_role(user.id, UserRole.BUYER)
        await _delete_callback_message(callback)
        await callback.message.answer("Меню покупателя", reply_markup=inline_menu(UserRole.BUYER))
        return True
    await deps.user_service.ensure_profile(
        user.id,
        full_name=user.full_name,
        username=user.username,
    )
    await state.set_state(MerchantApplicationState.choosing_banks)
    await state.update_data(
        banks=[],
        user_id=user.id,
        username=user.username,
    )
    kb = _bank_keyboard([])
    chat_id = callback.message.chat.id if callback.message else user.id
    await _delete_callback_message(callback)
    await callback.bot.send_message(
        chat_id,
        "Отлично, тогда немного вопросов для составления заявки.\n"
        "Какие банки из списка у вас присутствуют? Отметь и нажми «Готово».",
        reply_markup=kb.as_markup(),
    )
    return True


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    deps = get_deps()
    user = message.from_user
    if user:
        await deps.user_service.ensure_profile(
            user.id,
            full_name=user.full_name,
            username=user.username,
        )
    is_admin = bool(user and user.id in deps.config.admin_ids)
    is_moderator = bool(user and await deps.user_service.is_moderator(user.id))
    await message.answer(
        "Йо бро, это лучший бот BC Cash для обмена USDT сразу в кэш 🚀\n"
        "Выбери свою роль:",
        reply_markup=_role_keyboard().as_markup(),
    )
    role = await deps.user_service.role_of(user.id) if user else None
    if role == UserRole.BUYER:
        await message.answer(
            "Ты уже мерчант. Нажми «Меню», чтобы открыть действия.",
            reply_markup=base_keyboard(is_admin, is_moderator),
        )
    else:
        await message.answer(
            "После выбора роли появится кнопка «Меню».",
            reply_markup=ReplyKeyboardRemove(),
        )


@router.callback_query(F.data == ROLE_SELLER)
async def role_seller(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    await deps.user_service.ensure_profile(
        user.id,
        full_name=user.full_name,
        username=user.username,
    )
    await deps.user_service.set_role(user.id, UserRole.SELLER)
    is_admin = user.id in deps.config.admin_ids
    is_moderator = await deps.user_service.is_moderator(user.id)
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await callback.message.answer(
        "Отлично! переходи в меню",
        reply_markup=base_keyboard(is_admin, is_moderator),
    )
    await callback.answer("Роль продавца установлена")


@router.callback_query(F.data == ROLE_MERCHANT)
async def role_merchant(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _start_merchant_application(callback, state):
        await callback.answer()
        return
    await callback.answer()


@router.message(F.text == MenuButtons.SHOW_MENU.value)
async def open_menu(message: Message, state: FSMContext) -> None:
    deps = get_deps()
    user = message.from_user
    if not user:
        return
    role = await deps.user_service.role_of(user.id)
    if not role:
        await message.answer("Сначала выбери роль через /start")
        return
    title = "Меню продавца" if role == UserRole.SELLER else "Меню покупателя"
    sent = await message.answer(title, reply_markup=inline_menu(role))
    await state.update_data(back_action=None, last_menu_message_id=sent.message_id, last_menu_chat_id=sent.chat.id)


async def _handle_back_action(
    *,
    bot,
    chat_id: int,
    user,
    state: FSMContext,
    delete_message: Message | None = None,
) -> None:
    deps = get_deps()
    data = await state.get_data()
    if delete_message:
        with suppress(TelegramBadRequest):
            await delete_message.delete()
    last_message_id = data.get("last_menu_message_id")
    last_chat_id = data.get("last_menu_chat_id")
    if last_message_id and last_chat_id == chat_id:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id, last_message_id)
    action = data.get("back_action")
    if isinstance(action, str) and action.startswith("p2p:"):
        from cachebot.handlers import p2p as p2p_handlers

        if action == p2p_handlers.P2P_MENU:
            await p2p_handlers.send_p2p_menu(bot, chat_id, user.id, state=state)
            return
        if action == p2p_handlers.P2P_ADS:
            await p2p_handlers.send_p2p_ads(bot, chat_id, user.id, state=state)
            return
        if action == p2p_handlers.P2P_BUY:
            await p2p_handlers.send_p2p_list(bot, chat_id, user.id, side="buy", state=state)
            return
        if action == p2p_handlers.P2P_SELL:
            await p2p_handlers.send_p2p_list(bot, chat_id, user.id, side="sell", state=state)
            return
        if action.startswith(p2p_handlers.P2P_MY_DEALS_PAGE_PREFIX):
            page_str = action[len(p2p_handlers.P2P_MY_DEALS_PAGE_PREFIX) :]
            if page_str.isdigit():
                await p2p_handlers.send_p2p_my_deals(
                    bot, chat_id, user.id, page=int(page_str), state=state
                )
                return
        if action == p2p_handlers.P2P_MY_DEALS:
            await p2p_handlers.send_p2p_my_deals(bot, chat_id, user.id, page=0, state=state)
            return
    if isinstance(action, str) and action.startswith(MY_DEALS_PAGE_PREFIX):
        page_str = action[len(MY_DEALS_PAGE_PREFIX) :]
        if page_str.isdigit():
            await _render_my_deals(
                user.id,
                page=int(page_str),
                chat_id=chat_id,
                bot=bot,
                state=state,
            )
            return
    role = await deps.user_service.role_of(user.id)
    if not role:
        await bot.send_message(chat_id, "Сначала выбери роль через /start")
        return
    title = "Меню продавца" if role == UserRole.SELLER else "Меню покупателя"
    sent = await bot.send_message(chat_id, title, reply_markup=inline_menu(role))
    await state.update_data(last_menu_message_id=sent.message_id, last_menu_chat_id=sent.chat.id)


@router.message(F.text == "⬅️ Назад")
async def open_back(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if not user:
        return
    await _handle_back_action(
        bot=message.bot,
        chat_id=message.chat.id,
        user=user,
        state=state,
        delete_message=message,
    )


@router.callback_query(F.data == MenuAction.BACK.value)
async def inline_back(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    await _handle_back_action(
        bot=callback.bot,
        chat_id=callback.message.chat.id if callback.message else user.id,
        user=user,
        state=state,
        delete_message=callback.message,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bank:"), MerchantApplicationState.choosing_banks)
async def merchant_choose_banks(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    banks = set(data.get("banks") or [])
    action = callback.data.split(":", 1)[1]
    if action == "done":
        if not banks:
            await callback.answer("Отметь хотя бы один банк", show_alert=True)
            return
        await state.update_data(banks=list(banks))
        await state.set_state(MerchantApplicationState.personal_bank)
        await callback.message.answer(
            "Личные банки ли вы будете использовать?",
            reply_markup=_yes_no_keyboard("personal").as_markup(),
        )
        await callback.answer()
        return
    if action in BANK_OPTIONS:
        if action in banks:
            banks.remove(action)
        else:
            banks.add(action)
        await state.update_data(banks=list(banks))
        await callback.message.edit_reply_markup(
            reply_markup=_bank_keyboard(list(banks)).as_markup()
        )
    await callback.answer()


@router.callback_query(F.data.startswith("personal:"), MerchantApplicationState.personal_bank)
async def merchant_personal(callback: CallbackQuery, state: FSMContext) -> None:
    answer = callback.data.split(":", 1)[1]
    uses_personal = answer == "yes"
    await state.update_data(uses_personal=uses_personal)
    await state.set_state(MerchantApplicationState.risk_ack)
    await callback.message.answer(
        "Весь риск блокировки берёте на себя? "
        "Т.к. используете свой банк и деньги могут быть разблокированы.",
        reply_markup=_yes_no_keyboard("risk").as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("risk:"), MerchantApplicationState.risk_ack)
async def merchant_risk(callback: CallbackQuery, state: FSMContext) -> None:
    answer = callback.data.split(":", 1)[1]
    if answer == "no":
        await state.clear()
        await callback.message.answer(
            "К сожалению, мы не сможем сотрудничать. "
            "Если передумаете, заново напишите /start."
        )
        await callback.answer("Заявка остановлена")
        return
    await state.update_data(accepts_risk=True)
    await state.set_state(MerchantApplicationState.waiting_photos)
    await callback.message.answer("Пришлите, пожалуйста, скрины личных кабинетов.")
    await callback.answer()


@router.message(MerchantApplicationState.waiting_photos)
async def merchant_photos(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Нужно отправить фото. Попробуй снова.")
        return
    deps = get_deps()
    data = await state.get_data() or {}
    if not data.get("user_id"):
        await state.clear()
        await message.answer(
            "Похоже, заявка была сброшена. Напишите /start и выберите «Стать мерчантом» заново."
        )
        return
    photo_id = max(message.photo, key=lambda ph: ph.file_size or 0).file_id
    photo_ids = list(data.get("photo_file_ids") or [])
    photo_ids.append(photo_id)
    await state.clear()
    application = MerchantApplication(
        id=str(uuid4()),
        user_id=data["user_id"],
        username=data.get("username"),
        banks=list(data.get("banks") or []),
        uses_personal_bank=bool(data.get("uses_personal")),
        accepts_risk=True,
        photo_file_ids=photo_ids,
        created_at=datetime.now(timezone.utc),
    )
    await deps.user_service.add_application(application)
    await message.answer("Отлично! заявка уже на рассмотрении, ожидайте сообщения.")
    summary = _format_application(application)
    for admin_id in deps.config.admin_ids:
        try:
            await message.bot.send_photo(
                admin_id,
                photo_id,
                caption=summary,
            )
        except Exception:
            await message.bot.send_message(admin_id, summary)


@router.message(Command("rate"))
async def show_rate(message: Message) -> None:
    deps = get_deps()
    snapshot = await deps.rate_provider.snapshot()
    await message.answer(
        f"Текущий курс: 1 USDT = {_format_decimal(snapshot.usd_rate)} RUB\n"
        f"Комиссия: {snapshot.fee_percent}%"
    )


@router.message(Command("setrate"))
async def set_rate(message: Message) -> None:
    deps = get_deps()
    user = message.from_user
    if not user:
        return
    if user.id not in deps.config.admin_ids:
        await message.answer("Команда доступна только администраторам")
        return
    raw = _command_args(message).strip()
    if not raw:
        await message.answer("Укажи курс и опционально комиссию: /setrate 1.02 0.5")
        return
    try:
        usd_rate, fee_percent = _parse_rate_input(raw)
    except ValueError:
        await message.answer("Не удалось распознать числа")
        return
    await _apply_rate_change(deps, message, usd_rate, fee_percent)


@router.message(Command("balance"))
async def show_balance(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    await _send_balance(user.id, message.chat.id, message.bot)


@router.message(Command("profile"))
async def show_profile(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    await _send_profile(user, message.chat.id, message.bot)


@router.message(Command("mydeals"))
async def my_deals(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    await _render_my_deals(
        user.id,
        page=0,
        chat_id=message.chat.id,
        bot=message.bot,
    )


@router.message(F.text == MenuButtons.ADMIN_PANEL.value)
async def admin_panel_entry(message: Message) -> None:
    deps = get_deps()
    user = message.from_user
    if not user or user.id not in deps.config.admin_ids:
        await message.answer("Доступ только для владельцев")
        return
    await _send_admin_panel(message.chat.id, message.bot)


@router.message(F.text == MenuButtons.DISPUTES.value)
async def disputes_entry(message: Message) -> None:
    deps = get_deps()
    user = message.from_user
    if not user or not await _has_dispute_access(user.id, deps):
        await message.answer("Доступ только для модераторов")
        return
    await _send_disputes_list(message.chat.id, message.bot)


@router.message(Command("markpaid"))
async def mark_paid(message: Message) -> None:
    deps = get_deps()
    user = message.from_user
    if not user:
        return
    if user.id not in deps.config.admin_ids:
        await message.answer("Команда доступна только администраторам")
        return
    deal_id = _command_args(message).strip()
    if not deal_id:
        await message.answer("Укажи ID сделки")
        return
    await _mark_deal_paid(deps, message, deal_id)


# -- Menu action callbacks ---------------------------------------------------

@router.callback_query(F.data == MenuAction.BALANCE.value)
async def balance_from_menu(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    await state.update_data(back_action=None)
    chat_id = callback.message.chat.id if callback.message else user.id
    await _delete_callback_message(callback)
    await _send_balance(user.id, chat_id, callback.bot, state=state)
    await callback.answer()


@router.callback_query(F.data == BALANCE_WITHDRAW)
async def balance_withdraw_start(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    deps = get_deps()
    balance = await deps.deal_service.balance_of(user.id)
    if balance <= 0:
        await callback.answer("Баланс пуст", show_alert=True)
        return
    await state.set_state(WithdrawState.waiting_amount)
    await callback.message.answer(
        "Введи сумму в USDT для вывода. Комиссия "
        f"{deps.config.withdraw_fee_percent}% будет списана дополнительно. "
        "Для отмены напиши «Отмена».",
    )
    await callback.answer()


@router.callback_query(F.data.startswith(PROFILE_VIEW_PREFIX))
async def view_user_profile(callback: CallbackQuery) -> None:
    data = callback.data[len(PROFILE_VIEW_PREFIX) :]
    try:
        target_id = int(data)
    except ValueError:
        await callback.answer("Профиль недоступен", show_alert=True)
        return
    deps = get_deps()
    profile = await deps.user_service.profile_of(target_id)
    if not profile:
        await callback.answer("Профиль не найден", show_alert=True)
        return
    deals = await deps.deal_service.list_user_deals(target_id)
    reviews = await deps.review_service.list_for_user(target_id)
    role = await deps.user_service.role_of(target_id)
    show_private = bool(callback.from_user and callback.from_user.id in deps.config.admin_ids)
    builder = InlineKeyboardBuilder()
    builder.button(text="Отзывы", callback_data=f"{REVIEWS_VIEW_PREFIX}{target_id}:pos")
    await callback.message.answer(
        _format_profile(
            profile,
            deals,
            review_summary=_review_summary_text(reviews),
            role=role,
            show_private=show_private,
        ),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(REVIEWS_VIEW_PREFIX))
async def reviews_view(callback: CallbackQuery) -> None:
    payload = callback.data[len(REVIEWS_VIEW_PREFIX) :]
    if ":" in payload:
        raw_user_id, kind = payload.split(":", 1)
    else:
        raw_user_id, kind = payload, "pos"
    try:
        target_id = int(raw_user_id)
    except ValueError:
        await callback.answer()
        return
    deps = get_deps()
    reviews = await deps.review_service.list_for_user(target_id)
    text = await _format_reviews_list(target_id, reviews, kind, deps)
    markup = _reviews_keyboard(target_id, kind)
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith(REVIEWS_BACK_PREFIX))
async def reviews_back(callback: CallbackQuery) -> None:
    payload = callback.data[len(REVIEWS_BACK_PREFIX) :]
    try:
        target_id = int(payload)
    except ValueError:
        await callback.answer()
        return
    deps = get_deps()
    profile = await deps.user_service.profile_of(target_id)
    if not profile:
        await callback.answer("Профиль не найден", show_alert=True)
        return
    deals = await deps.deal_service.list_user_deals(target_id)
    reviews = await deps.review_service.list_for_user(target_id)
    role = await deps.user_service.role_of(target_id)
    show_private = bool(callback.from_user and callback.from_user.id in deps.config.admin_ids)
    builder = InlineKeyboardBuilder()
    builder.button(text="Отзывы", callback_data=f"{REVIEWS_VIEW_PREFIX}{target_id}:pos")
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await callback.message.answer(
        _format_profile(
            profile,
            deals,
            review_summary=_review_summary_text(reviews),
            role=role,
            show_private=show_private,
        ),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == MenuAction.SETTINGS.value)
async def settings_from_menu(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    await state.update_data(back_action=None)
    role = await deps.user_service.role_of(user.id)
    builder = InlineKeyboardBuilder()
    if role == UserRole.BUYER:
        builder.button(text="Продать USDT", callback_data=MenuAction.SETTINGS_SELLER.value)
    else:
        builder.button(text="Стать мерчантом", callback_data=MenuAction.SETTINGS_MERCHANT.value)
    builder.button(text="⬅️ Назад", callback_data=MenuAction.BACK.value)
    builder.adjust(1, 1)
    chat_id = callback.message.chat.id if callback.message else user.id
    await _delete_callback_message(callback)
    text = (
        "Раздел настроек. Здесь можно оставить заявку мерчанта."
        if role != UserRole.BUYER
        else "Ты уже мерчант. Можно открыть меню покупателя или перейти в режим продавца."
    )
    sent = await callback.bot.send_message(chat_id, text, reply_markup=builder.as_markup())
    await state.update_data(last_menu_message_id=sent.message_id, last_menu_chat_id=sent.chat.id)
    await callback.answer()


@router.callback_query(F.data == MenuAction.SETTINGS_MERCHANT.value)
async def settings_become_merchant(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    role = await deps.user_service.role_of(user.id)
    if role == UserRole.BUYER:
        chat_id = callback.message.chat.id if callback.message else user.id
        await _delete_callback_message(callback)
        sent = await callback.bot.send_message(chat_id, "Меню покупателя", reply_markup=inline_menu(UserRole.BUYER))
        await state.update_data(last_menu_message_id=sent.message_id, last_menu_chat_id=sent.chat.id)
        await callback.answer("Открываю меню мерчанта")
        return
    await _start_merchant_application(callback, state, deps)
    await callback.answer()


@router.callback_query(F.data == MenuAction.SETTINGS_SELLER.value)
async def settings_switch_to_seller(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    await deps.user_service.set_role(user.id, UserRole.SELLER)
    is_admin = user.id in deps.config.admin_ids
    is_moderator = await deps.user_service.is_moderator(user.id)
    chat_id = callback.message.chat.id if callback.message else user.id
    await _delete_callback_message(callback)
    sent = await callback.bot.send_message(
        chat_id,
        "Отлично! переходи в меню",
        reply_markup=base_keyboard(is_admin, is_moderator),
    )
    # reply menu is not tracked for back deletion
    await callback.answer("Переключено в режим продавца")




@router.callback_query(F.data == MenuAction.MY_DEALS.value)
async def my_deals_from_menu(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    await state.update_data(back_action=None)
    chat_id = callback.message.chat.id if callback.message else user.id
    await _delete_callback_message(callback)
    await _render_my_deals(
        user.id,
        page=0,
        chat_id=chat_id,
        bot=callback.bot,
        state=state,
    )
    await callback.answer()


@router.callback_query(F.data.startswith(MY_DEALS_PAGE_PREFIX))
async def my_deals_page(callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(MY_DEALS_PAGE_PREFIX) :]
    try:
        page = int(payload)
    except ValueError:
        await callback.answer()
        return
    await _render_my_deals(user.id, page=page, message=callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith(MY_DEALS_VIEW_PREFIX))
async def my_deal_detail(callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    deps = get_deps()
    await deps.user_service.ensure_profile(
        user.id,
        full_name=user.full_name,
        username=user.username,
    )
    payload = callback.data[len(MY_DEALS_VIEW_PREFIX) :]
    try:
        page_str, deal_id = payload.split(":", 1)
        page = int(page_str)
    except ValueError:
        await callback.answer()
        return
    await _render_deal_detail(
        user.id,
        deal_id=deal_id,
        page=page,
        message=callback.message,
    )
    await callback.answer()


@router.callback_query(F.data.startswith(DEAL_CANCEL_PREFIX))
async def deal_cancel_action(callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(DEAL_CANCEL_PREFIX) :]
    if payload.startswith("confirm:"):
        await deal_cancel_confirm(callback)
        return
    try:
        page_str, deal_id = payload.split(":", 1)
        page = int(page_str)
    except ValueError:
        await callback.answer()
        return
    deps = get_deps()
    deal = await deps.deal_service.get_deal(deal_id)
    if not deal:
        await callback.answer("Сделка не найдена", show_alert=True)
        return
    if deal.status == DealStatus.PAID and deal.qr_stage == QrStage.READY and deal.qr_photo_id:
        await callback.answer("На данном этапе нельзя отменить сделку.", show_alert=True)
        return
    allowed = (
        deal.buyer_id == user.id
        or (
            deal.status in {DealStatus.OPEN, DealStatus.RESERVED, DealStatus.PAID}
            and deal.seller_id == user.id
        )
        or user.id in deps.config.admin_ids
    )
    if not allowed:
        await callback.answer("Отмена доступна только участникам сделки", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Да, отменить",
        callback_data=f"{DEAL_CANCEL_CONFIRM_PREFIX}{page}:{deal_id}",
    )
    builder.button(
        text="Нет",
        callback_data=f"{MY_DEALS_VIEW_PREFIX}{page}:{deal_id}",
    )
    await _delete_callback_message(callback)
    await callback.message.answer(
        "Точно хотите отменить сделку? Деньги останутся у продавца.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(DEAL_CANCEL_CONFIRM_PREFIX))
async def deal_cancel_confirm(callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(DEAL_CANCEL_CONFIRM_PREFIX) :]
    try:
        page_str, deal_id = payload.split(":", 1)
        page = int(page_str)
    except ValueError:
        await callback.answer()
        return
    deps = get_deps()
    deal = await deps.deal_service.get_deal(deal_id)
    if deal and deal.status == DealStatus.PAID and deal.qr_stage == QrStage.READY and deal.qr_photo_id:
        await callback.answer("На данном этапе нельзя отменить сделку.", show_alert=True)
        return
    if deal and user.id == deal.seller_id and deal.status == DealStatus.RESERVED and deal.invoice_id:
        try:
            invoices = await deps.crypto_pay.fetch_invoices([deal.invoice_id])
            paid = next((item for item in invoices if item.status == "paid"), None)
            if paid:
                await deps.deal_service.mark_invoice_paid(deal.invoice_id)
                deal = await deps.deal_service.get_deal(deal_id)
        except Exception:
            pass
    try:
        deal, refund_amount = await _cancel_deal_core(user.id, deal_id)
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if deal.is_p2p and deal.advert_id:
        try:
            base_usdt = deal.usd_amount / deal.rate
            await deps.advert_service.restore_volume(deal.advert_id, base_usdt)
        except Exception:
            pass
    await callback.answer("Сделка отменена")
    await _delete_callback_message(callback)
    buyer_profile = None
    if deal.buyer_id:
        buyer_profile = await deps.user_service.profile_of(deal.buyer_id)
    seller_profile = await deps.user_service.profile_of(deal.seller_id)
    from cachebot.handlers.deal_flow import _send_deal_card

    try:
        await _send_deal_card(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            deal=deal,
            viewer_id=user.id,
            seller_profile=seller_profile,
            buyer_profile=buyer_profile,
            back_page=page,
            cancel_page=page,
        )
    except Exception:
        await callback.bot.send_message(
            callback.message.chat.id,
            f"✅ Сделка {deal.hashtag} отменена.",
        )
    if refund_amount is not None and user.id == deal.seller_id:
        await callback.bot.send_message(
            deal.seller_id,
            f"✅ Сделка {deal.hashtag} отменена.\n"
            f"На баланс зачислено {_format_decimal(refund_amount)} USDT (комиссия удержана).",
        )
    other = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    if other:
        who = "покупателем" if user.id == deal.buyer_id else "продавцом"
        suffix = (
            "Средства возвращены продавцу."
            if refund_amount is not None and user.id == deal.seller_id
            else "Рубли остаются у продавца."
        )
        await callback.bot.send_message(
            other,
            f"⚠️ Сделка {deal.hashtag} отменена {who}. {suffix}",
        )
    await callback.answer("Сделка отменена")


@router.callback_query(F.data.startswith(DEAL_COMPLETE_PREFIX))
async def deal_complete_action(callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(DEAL_COMPLETE_PREFIX) :]
    try:
        page_str, deal_id = payload.split(":", 1)
        page = int(page_str)
    except ValueError:
        await callback.answer()
        return
    try:
        await _complete_deal_core(user.id, deal_id, callback.bot)
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await _render_deal_detail(
        user.id,
        deal_id=deal_id,
        page=page,
        message=callback.message,
    )
    await callback.answer("Сделка завершена")


@router.callback_query(F.data.startswith(QR_REQUEST_PREFIX))
async def qr_request_start(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(QR_REQUEST_PREFIX) :]
    if ":" not in payload:
        await callback.answer()
        return
    source_raw, deal_id = payload.split(":", 1)
    source_type, page = _decode_qr_source(source_raw)
    deps = get_deps()
    deal = await deps.deal_service.get_deal(deal_id)
    if not deal or deal.buyer_id != user.id:
        await callback.answer("Нет доступа к сделке", show_alert=True)
        return
    if deal.status != DealStatus.PAID:
        await callback.answer("Сначала дождись оплаты Crypto Pay", show_alert=True)
        return
    if deal.qr_stage not in {QrStage.IDLE, QrStage.READY}:
        await callback.answer("Запрос уже в работе", show_alert=True)
        return
    allowed_banks = None
    if deal.advert_id:
        advert = await deps.advert_service.get_ad(deal.advert_id)
        if advert and advert.banks:
            allowed_banks = list(advert.banks)
    prompt = await callback.message.answer(
        f"Сделка {deal.hashtag}\n"
        "Какой банкомат нужен? Отметь доступные банки и нажми «Готово».",
        reply_markup=_qr_bank_keyboard([], allowed_banks).as_markup(),
    )
    await state.set_state(QrRequestState.selecting_banks)
    await state.update_data(
        qr_deal_id=deal.id,
        qr_source=source_type,
        qr_page=page,
        qr_prompt_id=prompt.message_id,
        qr_chat_id=prompt.chat.id,
        qr_selected=[],
        qr_allowed_banks=allowed_banks,
    )
    await callback.answer()


@router.callback_query(
    QrRequestState.selecting_banks, F.data.startswith(QR_BANK_SELECT_PREFIX)
)
async def qr_select_bank(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    data = await state.get_data()
    deal_id = data.get("qr_deal_id")
    if not deal_id:
        await state.clear()
        await callback.answer("Сессия истекла", show_alert=True)
        return
    action = callback.data[len(QR_BANK_SELECT_PREFIX) :]
    selected = set(data.get("qr_selected") or [])
    if action == "cancel":
        await state.clear()
        with suppress(TelegramBadRequest):
            await callback.message.delete()
        await callback.answer("Запрос отменен")
        return
    if action == "done":
        if not selected:
            await callback.answer("Отметь хотя бы один банк", show_alert=True)
            return
        deps = get_deps()
        try:
            deal = await deps.deal_service.start_qr_request(deal_id, user.id, list(selected))
        except Exception as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        await _notify_seller_qr_request(deal, list(selected), callback.bot)
        await state.clear()
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(
                f"Запрос на QR по сделке {deal.hashtag} отправлен продавцу.",
                reply_markup=None,
            )
        await callback.answer("Запрос отправлен")
        return
    allowed = data.get("qr_allowed_banks")
    if action not in BANK_OPTIONS:
        await callback.answer()
        return
    if allowed is not None and action not in allowed:
        await callback.answer()
        return
    if action in selected:
        selected.remove(action)
    else:
        selected.add(action)
    await state.update_data(qr_selected=list(selected))
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(
            reply_markup=_qr_bank_keyboard(sorted(selected), allowed).as_markup()
        )
    await callback.answer()


@router.callback_query(F.data.startswith(QR_SELLER_BANK_PREFIX))
async def qr_seller_choose_bank(callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(QR_SELLER_BANK_PREFIX) :]
    if ":" not in payload:
        await callback.answer()
        return
    deal_id, bank = payload.split(":", 1)
    deps = get_deps()
    try:
        deal = await deps.deal_service.seller_choose_qr_bank(deal_id, user.id, bank)
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if callback.message:
        builder = InlineKeyboardBuilder()
        for option in deal.qr_bank_options:
            prefix = "✅ " if option == bank else ""
            builder.button(
                text=f"{prefix}{bank_label(option)}",
                callback_data=f"{QR_SELLER_BANK_PREFIX}{deal.id}:{option}",
            )
        builder.adjust(1)
        with suppress(TelegramBadRequest):
            await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer("Банк выбран")
    builder = InlineKeyboardBuilder()
    builder.button(text="К сделке", callback_data=f"{DEAL_INFO_PREFIX}{deal.id}")
    await callback.message.answer(
        f"Выбран банкомат {bank_label(bank)} по сделке {deal.hashtag}.\n"
        "Перейди в меню сделки и нажми «Прикрепить QR», когда будешь готов.",
        reply_markup=builder.as_markup(),
    )
    if deal.buyer_id:
        buyer_builder = InlineKeyboardBuilder()
        buyer_builder.button(text="К сделке", callback_data=f"{DEAL_INFO_PREFIX}{deal.id}")
        await callback.bot.send_message(
            deal.buyer_id,
            f"Продавец выбрал банкомат {bank_label(bank)} по сделке {deal.hashtag}. "
            "Ожидайте отправления QR от продавца",
            reply_markup=buyer_builder.as_markup(),
        )


@router.callback_query(F.data.startswith(QR_SELLER_ATTACH_PREFIX))
async def qr_seller_attach(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(QR_SELLER_ATTACH_PREFIX) :]
    if ":" not in payload:
        await callback.answer()
        return
    source_raw, deal_id = payload.split(":", 1)
    _, page = _decode_qr_source(source_raw)
    deps = get_deps()
    deal = await deps.deal_service.get_deal(deal_id)
    if not deal:
        await callback.answer("Сделка недоступна", show_alert=True)
        return
    if deal.qr_stage == QrStage.AWAITING_SELLER_PHOTO:
        seller_key = StorageKey(
            bot_id=callback.bot.id,
            chat_id=deal.seller_id,
            user_id=deal.seller_id,
        )
        seller_state = FSMContext(storage=state.storage, key=seller_key)
        await seller_state.set_state(SellerQrUploadState.waiting_photo)
        await seller_state.update_data(qr_deal_id=deal.id)
        await callback.message.answer(
            "Прикрепи свежий QR-код в ответ на это сообщение.",
        )
        await callback.answer()
        return
    await callback.answer("Сейчас нельзя отправить QR", show_alert=True)


@router.callback_query(F.data.startswith(QR_SELLER_READY_PREFIX))
async def qr_seller_ready(callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(QR_SELLER_READY_PREFIX) :]
    if ":" not in payload:
        await callback.answer()
        return
    _, deal_id = payload.split(":", 1)
    deps = get_deps()
    try:
        deal = await deps.deal_service.seller_request_qr(deal_id, user.id)
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Готов",
        callback_data=f"{QR_BUYER_READY_PREFIX}info:{deal.id}",
    )
    if deal.buyer_id:
        await callback.bot.send_message(
            deal.buyer_id,
            f"Продавец готов отправить QR по сделке {deal.hashtag}. "
            "Нажми «Готов», как будешь готов сканировать.",
            reply_markup=builder.as_markup(),
        )
    await callback.message.answer("Запрос отправлен покупателю. Ожидаем подтверждение.")
    await callback.answer()


@router.callback_query(F.data.startswith(QR_BUYER_READY_PREFIX))
async def qr_buyer_ready(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(QR_BUYER_READY_PREFIX) :]
    if ":" not in payload:
        await callback.answer()
        return
    source_raw, deal_id = payload.split(":", 1)
    _, page = _decode_qr_source(source_raw)
    deps = get_deps()
    try:
        deal = await deps.deal_service.buyer_ready_for_qr(deal_id, user.id)
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    seller_key = StorageKey(
        bot_id=callback.bot.id,
        chat_id=deal.seller_id,
        user_id=deal.seller_id,
    )
    seller_state = FSMContext(storage=state.storage, key=seller_key)
    await seller_state.set_state(SellerQrUploadState.waiting_photo)
    await seller_state.update_data(qr_deal_id=deal.id)
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📎 Прикрепить QR",
        callback_data=f"{QR_SELLER_ATTACH_PREFIX}info:{deal.id}",
    )
    await callback.bot.send_message(
        deal.seller_id,
        f"Покупатель подтвердил готовность по сделке {deal.hashtag}.\n"
        "Прикрепи свежий QR-код через меню сделки либо кнопку ниже.",
        reply_markup=builder.as_markup(),
    )
    await _delete_callback_message(callback)
    from cachebot.handlers.deal_flow import _send_deal_card
    seller_profile = await deps.user_service.profile_of(deal.seller_id)
    buyer_profile = await deps.user_service.profile_of(deal.buyer_id) if deal.buyer_id else None
    await _send_deal_card(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        deal=deal,
        viewer_id=user.id,
        seller_profile=seller_profile,
        buyer_profile=buyer_profile,
        back_page=None,
        cancel_page=0,
    )
    await callback.answer("Готово")


@router.callback_query(F.data.startswith(QR_VIEW_PREFIX))
async def qr_view(callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(QR_VIEW_PREFIX) :]
    if ":" not in payload:
        await callback.answer()
        return
    _, deal_id = payload.split(":", 1)
    deps = get_deps()
    deal = await deps.deal_service.get_deal(deal_id)
    if not deal or user.id not in {deal.seller_id, deal.buyer_id}:
        await callback.answer("Сделка недоступна", show_alert=True)
        return
    if not deal.qr_photo_id:
        await callback.answer("QR еще не приложен", show_alert=True)
        return
    await callback.message.answer_photo(
        deal.qr_photo_id,
        caption=f"QR по сделке {deal.hashtag}",
    )
    await callback.answer()


@router.callback_query(F.data.startswith(QR_BUYER_DONE_PREFIX))
async def qr_buyer_done(callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(QR_BUYER_DONE_PREFIX) :]
    if ":" not in payload:
        await callback.answer()
        return
    source, deal_id = payload.split(":", 1)
    deps = get_deps()
    try:
        deal, completed = await deps.deal_service.confirm_buyer_cash(deal_id, user.id)
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if deal.seller_id:
        await callback.bot.send_message(
            deal.seller_id,
            f"Покупатель подтвердил снятие по сделке {deal.hashtag}.",
        )
    if completed:
        await _handle_deal_completed(deal, deps, callback.bot)
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    source_kind, back_page = _decode_qr_source(source)
    if user.id in {deal.seller_id, deal.buyer_id}:
        buyer_profile = None
        if deal.buyer_id:
            buyer_profile = await deps.user_service.profile_of(deal.buyer_id)
        seller_profile = await deps.user_service.profile_of(deal.seller_id)
        from cachebot.handlers.deal_flow import _send_deal_card

        await _send_deal_card(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            deal=deal,
            viewer_id=user.id,
            seller_profile=seller_profile,
            buyer_profile=buyer_profile,
            back_page=back_page if source_kind == "list" else None,
            cancel_page=back_page if source_kind == "list" else None,
        )
    await callback.answer("Отметили статус")


@router.callback_query(F.data.startswith(QR_SELLER_DONE_PREFIX))
async def qr_seller_done(callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(QR_SELLER_DONE_PREFIX) :]
    if ":" not in payload:
        await callback.answer()
        return
    source, deal_id = payload.split(":", 1)
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    text = (
        "Все деньги были получены?\n"
        "⚠️ Нажимая «Да», вы подтверждаете перевод USDT покупателю."
    )
    await callback.bot.send_message(
        callback.message.chat.id,
        text,
        reply_markup=_seller_cash_confirm_keyboard(step=1, source=source, deal_id=deal_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(REVIEW_START_PREFIX))
async def review_start(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    deal_id = callback.data[len(REVIEW_START_PREFIX) :]
    deps = get_deps()
    try:
        deal = await deps.deal_service.get_deal(deal_id)
    except Exception:
        deal = None
    if not deal or user.id not in {deal.seller_id, deal.buyer_id}:
        await callback.answer("Сделка недоступна", show_alert=True)
        return
    if deal.status != DealStatus.COMPLETED:
        await callback.answer("Сделка еще не завершена", show_alert=True)
        return
    target_id = deal.buyer_id if user.id == deal.seller_id else deal.seller_id
    if not target_id:
        await callback.answer("Сделка недоступна", show_alert=True)
        return
    review = await deps.review_service.review_between(user.id, target_id)
    if review:
        await callback.answer("Отзыв уже оставлен", show_alert=True)
        return
    await state.clear()
    await state.update_data(review_deal_id=deal.id)
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    builder = InlineKeyboardBuilder()
    builder.button(text="👍 Положительная", callback_data=f"{REVIEW_RATE_PREFIX}{deal.id}:1")
    builder.button(text="👎 Отрицательная", callback_data=f"{REVIEW_RATE_PREFIX}{deal.id}:-1")
    builder.adjust(1)
    await callback.bot.send_message(
        callback.message.chat.id,
        "Как прошла ваша сделка?\n"
        "Оцените ее, ваше мнение очень важно!",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(REVIEW_RATE_PREFIX))
async def review_rate(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(REVIEW_RATE_PREFIX) :]
    if ":" not in payload:
        await callback.answer()
        return
    deal_id, raw_rating = payload.split(":", 1)
    try:
        rating = int(raw_rating)
    except ValueError:
        await callback.answer()
        return
    deps = get_deps()
    deal = await deps.deal_service.get_deal(deal_id)
    if user.id not in {deal.seller_id, deal.buyer_id}:
        await callback.answer("Нет доступа", show_alert=True)
        return
    target_id = deal.buyer_id if user.id == deal.seller_id else deal.seller_id
    if not target_id:
        await callback.answer("Нет второй стороны", show_alert=True)
        return
    await state.update_data(review_deal_id=deal.id, review_rating=rating, review_target_id=target_id)
    await state.set_state(ReviewState.waiting_comment)
    builder = InlineKeyboardBuilder()
    builder.button(text="Пропустить", callback_data=f"{REVIEW_SKIP_PREFIX}{deal.id}")
    await callback.message.edit_text(
        "Хотели бы добавить какой-то комментарий к сделке?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(REVIEW_SKIP_PREFIX))
async def review_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await _finalize_review(callback.from_user, callback, state, comment=None)


@router.message(ReviewState.waiting_comment)
async def review_comment(message: Message, state: FSMContext) -> None:
    comment = (message.text or "").strip()
    if not comment:
        await message.answer("Напиши комментарий или нажми «Пропустить».")
        return
    await _finalize_review(message.from_user, message, state, comment=comment)

@router.callback_query(F.data.startswith(QR_SELLER_CONFIRM_STEP1_PREFIX))
async def qr_seller_confirm_step1(callback: CallbackQuery) -> None:
    payload = callback.data[len(QR_SELLER_CONFIRM_STEP1_PREFIX) :]
    if payload.count(":") < 2:
        await callback.answer()
        return
    source, deal_id, decision = payload.split(":", 2)
    if decision != "yes":
        with suppress(TelegramBadRequest):
            await callback.message.delete()
        await callback.answer("Отменено")
        return
    text = "Подтвердите перевод."
    await callback.message.edit_text(
        text,
        reply_markup=_seller_cash_confirm_keyboard(step=2, source=source, deal_id=deal_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(QR_SELLER_CONFIRM_STEP2_PREFIX))
async def qr_seller_confirm_step2(callback: CallbackQuery) -> None:
    payload = callback.data[len(QR_SELLER_CONFIRM_STEP2_PREFIX) :]
    if payload.count(":") < 2:
        await callback.answer()
        return
    source, deal_id, decision = payload.split(":", 2)
    if decision != "yes":
        with suppress(TelegramBadRequest):
            await callback.message.delete()
        await callback.answer("Отменено")
        return
    deps = get_deps()
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    try:
        deal, completed = await deps.deal_service.confirm_seller_cash(deal_id, user.id)
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    if deal.buyer_id:
        builder = InlineKeyboardBuilder()
        builder.button(text="В сделку", callback_data=f"{DEAL_INFO_PREFIX}{deal.id}")
        await callback.bot.send_message(
            deal.buyer_id,
            f"Продавец подтвердил получение наличных по сделке {deal.hashtag}.",
            reply_markup=builder.as_markup(),
        )
    if completed:
        await _handle_deal_completed(deal, deps, callback.bot)
    source_kind, back_page = _decode_qr_source(source)
    if user.id in {deal.seller_id, deal.buyer_id}:
        buyer_profile = None
        if deal.buyer_id:
            buyer_profile = await deps.user_service.profile_of(deal.buyer_id)
        seller_profile = await deps.user_service.profile_of(deal.seller_id)
        from cachebot.handlers.deal_flow import _send_deal_card

        await _send_deal_card(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            deal=deal,
            viewer_id=user.id,
            seller_profile=seller_profile,
            buyer_profile=buyer_profile,
            back_page=back_page if source_kind == "list" else None,
            cancel_page=back_page if source_kind == "list" else None,
        )
    await callback.answer("Готово")


@router.callback_query(F.data.startswith(DISPUTE_OPEN_PREFIX))
async def dispute_open(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    deal_id = callback.data[len(DISPUTE_OPEN_PREFIX) :]
    deps = get_deps()
    deal = await deps.deal_service.get_deal(deal_id)
    if not deal or user.id not in {deal.seller_id, deal.buyer_id}:
        await callback.answer("Сделка недоступна", show_alert=True)
        return
    if deal.status != DealStatus.PAID:
        await callback.answer("Спор можно открыть только после оплаты", show_alert=True)
        return
    if deal.dispute_opened_by or deal.status == DealStatus.DISPUTE:
        await callback.answer("Спор уже открыт", show_alert=True)
        return
    now = datetime.now(timezone.utc)
    if deal.dispute_available_at and now < deal.dispute_available_at:
        remaining = deal.dispute_available_at - now
        minutes = max(1, int(remaining.total_seconds() // 60) + 1)
        await callback.answer(
            f"Открыть спор можно через {minutes} мин.",
            show_alert=True,
        )
        return
    await state.clear()
    await state.update_data(dispute_deal_id=deal.id)
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    builder = InlineKeyboardBuilder()
    builder.button(text="Не получил нал", callback_data=f"{DISPUTE_REASON_PREFIX}{deal.id}:no_cash")
    builder.button(
        text="Получил не всю сумму",
        callback_data=f"{DISPUTE_REASON_PREFIX}{deal.id}:partial",
    )
    builder.button(text="Другая причина", callback_data=f"{DISPUTE_REASON_PREFIX}{deal.id}:other")
    builder.adjust(1)
    await callback.bot.send_message(
        callback.message.chat.id,
        "Какая причина открытия спора?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(DISPUTE_APPEND_PREFIX))
async def dispute_append_start(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    deal_id = callback.data[len(DISPUTE_APPEND_PREFIX) :]
    deps = get_deps()
    deal = await deps.deal_service.get_deal(deal_id)
    if not deal or user.id != deal.buyer_id:
        await callback.answer("Нет доступа", show_alert=True)
        return
    if deal.status != DealStatus.DISPUTE or deal.dispute_opened_by != deal.seller_id:
        await callback.answer("Нельзя дополнить спор", show_alert=True)
        return
    dispute = await deps.dispute_service.dispute_for_deal(deal.id)
    if not dispute:
        await callback.answer(f"Спор не найден. debug={dispute_id}", show_alert=True)
        return
    await state.clear()
    await state.set_state(DisputeState.waiting_append_text)
    await state.update_data(dispute_deal_id=deal.id)
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await callback.bot.send_message(
        callback.message.chat.id,
        "Что произошло? Опиши ситуацию одним сообщением.",
    )
    await callback.answer()


@router.callback_query(F.data.startswith(DISPUTE_REASON_PREFIX))
async def dispute_reason(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    if not user:
        await callback.answer()
        return
    payload = callback.data[len(DISPUTE_REASON_PREFIX) :]
    if ":" not in payload:
        await callback.answer()
        return
    deal_id, reason_key = payload.split(":", 1)
    if reason_key == "other":
        await state.set_state(DisputeState.waiting_reason_text)
        await state.update_data(dispute_deal_id=deal_id, dispute_reason="Другая причина")
        await callback.message.edit_text("Опиши причину спора одним сообщением.")
        await callback.answer()
        return
    reason_label = "Не получил нал" if reason_key == "no_cash" else "Получил не всю сумму"
    await state.set_state(DisputeState.waiting_evidence)
    await state.update_data(dispute_deal_id=deal_id, dispute_reason=reason_label)
    await callback.message.edit_text(
        "Прикрепи видео из личного кабинета или другие доказательства.",
        reply_markup=None,
    )
    await callback.answer()


@router.message(DisputeState.waiting_reason_text)
async def dispute_reason_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Опиши причину спора текстом.")
        return
    data = await state.get_data()
    await state.set_state(DisputeState.waiting_evidence)
    await state.update_data(dispute_comment=text, dispute_reason=data.get("dispute_reason"))
    await message.answer(
        "Прикрепи видео из личного кабинета или другие доказательства.",
        reply_markup=None,
    )


@router.message(DisputeState.waiting_append_text)
async def dispute_append_text(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if not user:
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Опиши ситуацию текстом.")
        return
    data = await state.get_data()
    deal_id = data.get("dispute_deal_id")
    if not deal_id:
        await state.clear()
        await message.answer("Не удалось найти спор.")
        return
    deps = get_deps()
    dispute = await deps.dispute_service.dispute_for_deal(deal_id)
    if not dispute:
        await state.clear()
        await message.answer("Спор не найден.")
        return
    await deps.dispute_service.append_message(dispute.id, user.id, text)
    await state.set_state(DisputeState.waiting_append_evidence)
    await message.answer("Прикрепи видео с личного кабинета банка или другое доказательство.")


@router.message(DisputeState.waiting_append_evidence)
async def dispute_append_evidence(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if not user:
        return
    data = await state.get_data()
    deal_id = data.get("dispute_deal_id")
    if not deal_id:
        await state.clear()
        await message.answer("Не удалось найти спор.")
        return
    deps = get_deps()
    dispute = await deps.dispute_service.dispute_for_deal(deal_id)
    if not dispute:
        await state.clear()
        await message.answer("Спор не найден.")
        return
    evidence: EvidenceItem | None = None
    if message.video:
        evidence = EvidenceItem(kind="video", file_id=message.video.file_id, author_id=user.id)
    elif message.photo:
        evidence = EvidenceItem(kind="photo", file_id=message.photo[-1].file_id, author_id=user.id)
    elif message.document:
        evidence = EvidenceItem(kind="document", file_id=message.document.file_id, author_id=user.id)
    if not evidence:
        await message.answer("Прикрепи фото или видео как доказательство.")
        return
    await deps.dispute_service.append_evidence(dispute.id, evidence)
    await state.clear()
    await message.answer("Спасибо, материалы добавлены к спору.")


@router.message(DisputeState.waiting_evidence)
async def dispute_evidence(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if not user:
        return
    data = await state.get_data()
    deal_id = data.get("dispute_deal_id")
    reason = data.get("dispute_reason")
    comment = data.get("dispute_comment")
    if not deal_id or not reason:
        await state.clear()
        await message.answer("Не удалось открыть спор, попробуй снова.")
        return
    evidence: EvidenceItem | None = None
    if message.video:
        evidence = EvidenceItem(kind="video", file_id=message.video.file_id, author_id=user.id)
    elif message.photo:
        evidence = EvidenceItem(kind="photo", file_id=message.photo[-1].file_id, author_id=user.id)
    elif message.document:
        evidence = EvidenceItem(kind="document", file_id=message.document.file_id, author_id=user.id)
    if not evidence:
        await message.answer("Прикрепи фото или видео как доказательство.")
        return
    deps = get_deps()
    deal = await deps.deal_service.get_deal(deal_id)
    if not deal or user.id not in {deal.seller_id, deal.buyer_id}:
        await state.clear()
        await message.answer("Сделка недоступна.")
        return
    try:
        await deps.dispute_service.open_dispute(
            deal_id=deal.id,
            opened_by=user.id,
            reason=reason,
            comment=comment,
            evidence=[evidence],
        )
        await deps.deal_service.open_dispute(deal.id, user.id)
    except Exception as exc:
        await state.clear()
        await message.answer(f"Не удалось открыть спор: {exc}")
        return
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="К сделке", callback_data=f"{DEAL_INFO_PREFIX}{deal.id}")
    await message.answer(
        "Спор открыт. Он находится на рассмотрении.\n"
        "Ожидайте решения модератора.",
        reply_markup=builder.as_markup(),
    )
    notify_text = (
        f"Открыт спор по сделке {deal.hashtag}. "
        "Ожидайте решения модератора."
    )
    if deal.buyer_id and deal.buyer_id != user.id:
        await message.bot.send_message(
            deal.buyer_id, notify_text, reply_markup=builder.as_markup()
        )
    if deal.seller_id != user.id:
        await message.bot.send_message(
            deal.seller_id, notify_text, reply_markup=builder.as_markup()
        )


@router.callback_query(F.data == ADMIN_PANEL_MENU)
async def admin_panel_callback(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await _send_admin_panel(callback.message.chat.id, callback.bot)
    await callback.answer()


@router.callback_query(F.data == ADMIN_PANEL_APPS)
async def admin_panel_apps(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await _send_applications_list(callback.message.chat.id, callback.bot)
    await callback.answer()


@router.callback_query(F.data == ADMIN_PANEL_MODERATORS)
async def admin_panel_moderators(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await _send_moderators_list(callback.message.chat.id, callback.bot)
    await callback.answer()


@router.callback_query(F.data == ADMIN_PANEL_RATES)
async def admin_panel_rates(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    snapshot = await deps.rate_provider.snapshot()
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Изменить курс", callback_data=ADMIN_RATE_SET),
        InlineKeyboardButton(text="Изменить комиссию", callback_data=ADMIN_FEE_SET),
    )
    builder.row(
        InlineKeyboardButton(text="➕ Добавить модератора", callback_data=ADMIN_MODERATOR_ADD),
    )
    text = (
        "<b>Управление</b>\n"
        f"Текущий курс: 1 USDT = {_format_decimal(snapshot.usd_rate)} RUB\n"
        f"Комиссия: {snapshot.fee_percent}%\n"
        f"Комиссия на вывод: {deps.config.withdraw_fee_percent}%"
    )
    await callback.bot.send_message(
        callback.message.chat.id,
        text,
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == ADMIN_MODERATOR_ADD)
async def admin_moderator_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(ModeratorAdminState.waiting_username)
    await callback.message.answer("Введи @username модератора. Для отмены напиши «Отмена».")
    await callback.answer()


@router.message(ModeratorAdminState.waiting_username)
async def admin_moderator_add_finish(message: Message, state: FSMContext) -> None:
    deps = get_deps()
    user = message.from_user
    if not user or user.id not in deps.config.admin_ids:
        await message.answer("Нет доступа")
        await state.clear()
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Укажи username.")
        return
    if text.lower() == "отмена":
        await state.clear()
        await message.answer("Отмена.")
        return
    profile = await deps.user_service.profile_by_username(text)
    if not profile:
        await message.answer("Пользователь не найден. Попроси его написать /start.")
        return
    await deps.user_service.add_moderator(profile.user_id)
    await state.clear()
    await message.answer(f"✅ Модератор добавлен: @{profile.username}")


@router.callback_query(F.data.startswith(ADMIN_MODERATOR_VIEW_PREFIX))
async def admin_moderator_view(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    raw = callback.data[len(ADMIN_MODERATOR_VIEW_PREFIX) :]
    try:
        moderator_id = int(raw)
    except ValueError:
        await callback.answer()
        return
    profile = await deps.user_service.profile_of(moderator_id)
    resolved_count = await deps.dispute_service.count_resolved_by(moderator_id)
    in_work = len(await deps.dispute_service.list_assigned_open(moderator_id))
    name = "—"
    username = "—"
    if profile:
        name = profile.full_name or "—"
        if profile.username:
            username = f"@{profile.username}"
    text = (
        "<b>Модератор</b>\n"
        f"Имя: {escape(name)}\n"
        f"Юзернейм: {escape(username)}\n"
        f"В работе: {in_work}\n"
        f"Решено споров: {resolved_count}"
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Споры",
            callback_data=f"{ADMIN_MODERATOR_DISPUTES_PREFIX}{moderator_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="Исключить",
            callback_data=f"{ADMIN_MODERATOR_REMOVE_PREFIX}{moderator_id}",
        )
    )
    await callback.message.answer(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_MODERATOR_REMOVE_PREFIX))
async def admin_moderator_remove(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    raw = callback.data[len(ADMIN_MODERATOR_REMOVE_PREFIX) :]
    try:
        moderator_id = int(raw)
    except ValueError:
        await callback.answer()
        return
    await deps.user_service.remove_moderator(moderator_id)
    await callback.answer("Исключен")
    await _send_moderators_list(callback.message.chat.id, callback.bot)


@router.callback_query(F.data.startswith(ADMIN_MODERATOR_DISPUTES_PREFIX))
async def admin_moderator_disputes(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    raw = callback.data[len(ADMIN_MODERATOR_DISPUTES_PREFIX) :]
    try:
        moderator_id = int(raw)
    except ValueError:
        await callback.answer()
        return
    await _send_moderator_disputes(callback.message.chat.id, callback.bot, moderator_id)
    await callback.answer()


@router.callback_query(F.data.startswith(DISPUTE_LIST_PREFIX))
async def dispute_list(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or not await _has_dispute_access(user.id, deps):
        await callback.answer("Нет доступа", show_alert=True)
        return
    open_disputes = await deps.dispute_service.list_open_disputes_for(user.id)
    for item in open_disputes:
        deal = await deps.deal_service.get_deal(item.deal_id)
        if deal and deal.status == DealStatus.COMPLETED:
            await deps.dispute_service.resolve_for_deal(item.deal_id, resolved_by=0)
    await _send_disputes_list(callback.message.chat.id, callback.bot)
    await callback.answer()


@router.callback_query(F.data.startswith(DISPUTE_VIEW_PREFIX))
async def dispute_view(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or not await _has_dispute_access(user.id, deps):
        await callback.answer("Нет доступа", show_alert=True)
        return
    dispute_id = callback.data[len(DISPUTE_VIEW_PREFIX) :]
    if not dispute_id:
        await callback.answer("Спор не найден", show_alert=True)
        return
    dispute = await deps.dispute_service.dispute_by_id(dispute_id)
    if not dispute:
        await callback.answer(f"Спор не найден. debug={dispute_id}", show_alert=True)
        return
    deal = await deps.deal_service.get_deal(dispute.deal_id)
    if not deal:
        await callback.answer("Сделка не найдена", show_alert=True)
        return
    if dispute.assigned_to and dispute.assigned_to != user.id and user.id not in deps.config.admin_ids:
        await callback.answer("Спор уже в работе", show_alert=True)
        return
    seller_profile = await deps.user_service.profile_of(deal.seller_id)
    buyer_profile = await deps.user_service.profile_of(deal.buyer_id) if deal.buyer_id else None
    if dispute.assigned_to is None:
        text = _format_dispute_detail(deal, dispute, seller_profile, buyer_profile)
        messages_text = await _format_dispute_messages(dispute, deps)
        text = f"{text}\n\n{messages_text}"
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="🛠 Взять в работу",
                callback_data=f"{DISPUTE_TAKE_PREFIX}{dispute.id}",
            )
        )
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
        await callback.answer()
        return
    await state.clear()
    await state.update_data(
        dispute_id=dispute.id,
        deal_id=dispute.deal_id,
        buyer_amount=Decimal("0"),
        seller_amount=Decimal("0"),
    )
    text = _format_dispute_admin_card(
        deal, dispute, seller_profile, buyer_profile, Decimal("0"), Decimal("0")
    )
    markup = _dispute_admin_keyboard(dispute.id)
    sent = await callback.message.answer(text, reply_markup=markup)
    await state.update_data(
        dispute_menu_chat_id=sent.chat.id,
        dispute_menu_message_id=sent.message_id,
    )
    await callback.answer()


@router.callback_query(F.data.startswith(DISPUTE_EVIDENCE_VIEW_PREFIX))
async def dispute_evidence_view(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or not await _has_dispute_access(user.id, deps):
        await callback.answer("Нет доступа", show_alert=True)
        return
    payload = callback.data[len(DISPUTE_EVIDENCE_VIEW_PREFIX) :]
    role = None
    dispute_id = None
    if payload in {"seller", "buyer"}:
        role = payload
        data = await state.get_data()
        dispute_id = data.get("dispute_id")
    elif ":" in payload:
        dispute_id, role = payload.split(":", 1)
    else:
        dispute_id = payload
    dispute = await deps.dispute_service.dispute_by_id(dispute_id)
    if not dispute:
        await callback.answer("Спор не найден", show_alert=True)
        return
    if not dispute.evidence:
        await callback.answer("Доказательств нет", show_alert=True)
        return
    deal = await deps.deal_service.get_deal(dispute.deal_id)
    if role in {"seller", "buyer"} and deal:
        target_id = deal.seller_id if role == "seller" else deal.buyer_id
        items = [item for item in dispute.evidence if item.author_id == target_id]
    else:
        items = dispute.evidence
    if not items:
        await callback.answer("Доказательств нет", show_alert=True)
        return
    for item in items:
        author_name, author_role = await _dispute_author_label(
            item.author_id, deal, deps
        )
        caption = f"От: {author_name} ({author_role})"
        if item.kind == "photo":
            await callback.bot.send_photo(
                callback.message.chat.id, item.file_id, caption=caption
            )
        elif item.kind == "video":
            await callback.bot.send_video(
                callback.message.chat.id, item.file_id, caption=caption
            )
        else:
            await callback.bot.send_document(
                callback.message.chat.id, item.file_id, caption=caption
            )
    await callback.answer()


@router.callback_query(
    F.data.startswith(DISPUTE_CLOSE_PREFIX)
    & ~F.data.startswith(DISPUTE_CLOSE_SIDE_PREFIX)
    & ~F.data.startswith(DISPUTE_CLOSE_BUYER_PREFIX)
    & ~F.data.startswith(DISPUTE_CLOSE_SELLER_PREFIX)
    & ~F.data.startswith(DISPUTE_CLOSE_CONFIRM_PREFIX)
)
async def dispute_close_start(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or not await _has_dispute_access(user.id, deps):
        await callback.answer("Нет доступа", show_alert=True)
        return
    logging.info("DISPUTE_CLOSE_START payload=%s", callback.data)
    dispute_id = callback.data[len(DISPUTE_CLOSE_PREFIX) :]
    dispute = await deps.dispute_service.dispute_by_id(dispute_id)
    if not dispute and dispute_id:
        dispute = await deps.dispute_service.dispute_for_deal(dispute_id)
    if not dispute:
        await callback.answer("Спор не найден", show_alert=True)
        return
    deal = await deps.deal_service.get_deal(dispute.deal_id)
    if not deal:
        await callback.answer("Сделка не найдена", show_alert=True)
        return
    seller_profile = await deps.user_service.profile_of(deal.seller_id)
    buyer_profile = await deps.user_service.profile_of(deal.buyer_id) if deal.buyer_id else None
    data = await state.get_data()
    buyer_amount = Decimal(str(data.get("buyer_amount", "0")))
    seller_amount = Decimal(str(data.get("seller_amount", "0")))
    await state.clear()
    await state.update_data(
        dispute_id=dispute.id,
        deal_id=dispute.deal_id,
        buyer_amount=buyer_amount,
        seller_amount=seller_amount,
    )
    text = _format_dispute_admin_card(
        deal, dispute, seller_profile, buyer_profile, buyer_amount, seller_amount
    )
    markup = _dispute_admin_keyboard(dispute.id)
    sent = await callback.message.answer(text, reply_markup=markup)
    await state.update_data(
        dispute_menu_chat_id=sent.chat.id,
        dispute_menu_message_id=sent.message_id,
    )
    await callback.answer()


@router.callback_query(F.data.startswith(DISPUTE_CLOSE_SIDE_PREFIX))
async def dispute_close_side(callback: CallbackQuery, state: FSMContext) -> None:
    debug_payload = callback.data
    payload = callback.data[len(DISPUTE_CLOSE_SIDE_PREFIX) :]
    dispute_id = None
    side = payload
    if ":" in payload:
        dispute_id, side = payload.split(":", 1)
    if side not in {"buyer", "seller"}:
        await callback.answer()
        return
    deps = get_deps()
    if not dispute_id:
        data = await state.get_data()
        dispute_id = data.get("dispute_id")
    dispute = await deps.dispute_service.dispute_by_id(dispute_id) if dispute_id else None
    if not dispute:
        if dispute_id:
            dispute = await deps.dispute_service.dispute_for_deal(dispute_id)
    if not dispute:
        data = await state.get_data()
        deal_id = data.get("deal_id")
        if deal_id:
            dispute = await deps.dispute_service.dispute_for_deal(deal_id)
        if not dispute:
            open_disputes = await deps.dispute_service.list_open_disputes()
            if len(open_disputes) == 1:
                dispute = open_disputes[0]
            elif open_disputes:
                open_disputes.sort(key=lambda item: item.opened_at, reverse=True)
                dispute = open_disputes[0]
    if not dispute:
        await callback.answer(f"Спор не найден. debug={debug_payload}", show_alert=True)
        return
    await state.update_data(dispute_id=dispute.id, deal_id=dispute.deal_id, winner_side=side)
    await state.set_state(DisputeAdminState.buyer_full)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Да",
            callback_data=f"{DISPUTE_CLOSE_BUYER_PREFIX}need:yes",
        ),
        InlineKeyboardButton(
            text="Нет",
            callback_data=f"{DISPUTE_CLOSE_BUYER_PREFIX}need:no",
        ),
    )
    await callback.message.answer(
        "Нужно ли отправить USDT мерчанту?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(DISPUTE_CLOSE_BUYER_PREFIX))
async def dispute_close_buyer_flow(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    data = await state.get_data()
    payload = callback.data[len(DISPUTE_CLOSE_BUYER_PREFIX) :]
    dispute_id = None
    action = payload
    if ":" in payload:
        head, tail = payload.split(":", 1)
        if head in {"need", "full"}:
            action = payload
        else:
            dispute_id, action = head, tail
    deal_id = data.get("deal_id")
    if not deal_id:
        if not dispute_id:
            dispute_id = data.get("dispute_id")
        if not dispute_id:
            await callback.answer("Спор не найден", show_alert=True)
            return
        dispute = await deps.dispute_service.dispute_by_id(dispute_id)
        if not dispute:
            await callback.answer("Спор не найден", show_alert=True)
            return
        deal_id = dispute.deal_id
        await state.update_data(dispute_id=dispute.id, deal_id=deal_id)
    deal = await deps.deal_service.get_deal(deal_id)
    if not deal:
        await callback.answer("Сделка не найдена", show_alert=True)
        return
    if action == "need:no":
        await state.update_data(buyer_amount=Decimal("0"))
        await state.set_state(DisputeAdminState.seller_full)
        await _ask_seller_payout(callback, state, dispute_id)
        await callback.answer()
        return
    if action == "need:yes":
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="Да",
                callback_data=f"{DISPUTE_CLOSE_BUYER_PREFIX}full:yes",
            ),
            InlineKeyboardButton(
                text="Указать сумму",
                callback_data=f"{DISPUTE_CLOSE_BUYER_PREFIX}full:no",
            ),
        )
        await callback.message.answer(
            f"Всю сумму ({_format_decimal(deal.usdt_amount)} USDT) отправить мерчанту?",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return
    if action == "full:yes":
        await state.update_data(buyer_amount=deal.usdt_amount)
        await state.set_state(DisputeAdminState.seller_full)
        await _ask_seller_payout(callback, state, dispute_id)
        await callback.answer()
        return
    if action == "full:no":
        await state.set_state(DisputeAdminState.buyer_amount)
        await callback.message.answer("Введи сумму USDT для мерчанта.")
        await callback.answer()


@router.message(DisputeAdminState.buyer_amount)
async def dispute_buyer_amount(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        amount = Decimal(text.replace(",", "."))
    except Exception:
        await message.answer("Не смог распознать число, попробуй снова.")
        return
    if amount < 0:
        await message.answer("Сумма не может быть отрицательной.")
        return
    deps = get_deps()
    data = await state.get_data()
    deal = await deps.deal_service.get_deal(data.get("deal_id", ""))
    if not deal:
        await state.clear()
        await message.answer("Сделка не найдена.")
        return
    seller_amount = Decimal(str(data.get("seller_amount", "0")))
    available = deal.usdt_amount - seller_amount
    if amount > available:
        await message.answer(
            f"Сумма превышает доступный остаток ({_format_decimal(available)} USDT)."
        )
        return
    with suppress(TelegramBadRequest):
        await message.delete()
    prompt_id = data.get("dispute_payout_prompt_id")
    if prompt_id:
        with suppress(TelegramBadRequest):
            await message.bot.delete_message(message.chat.id, prompt_id)
    prompt_id = data.get("dispute_payout_prompt_id")
    if prompt_id:
        with suppress(TelegramBadRequest):
            await message.bot.delete_message(message.chat.id, prompt_id)
    await state.update_data(buyer_amount=amount)
    await state.set_state(DisputeAdminState.confirm)
    await _refresh_dispute_admin_menu(message.bot, state)
    await message.answer(
        f"✅ Выплата мерчанту установлена: {_format_decimal(amount)} USDT."
    )


@router.callback_query(F.data.startswith(DISPUTE_CLOSE_SELLER_PREFIX))
async def dispute_close_seller_flow(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    data = await state.get_data()
    payload = callback.data[len(DISPUTE_CLOSE_SELLER_PREFIX) :]
    dispute_id = None
    action = payload
    if ":" in payload:
        head, tail = payload.split(":", 1)
        if head in {"need", "full"}:
            action = payload
        else:
            dispute_id, action = head, tail
    deal_id = data.get("deal_id")
    if not deal_id:
        if not dispute_id:
            dispute_id = data.get("dispute_id")
        if not dispute_id:
            await callback.answer("Спор не найден", show_alert=True)
            return
        dispute = await deps.dispute_service.dispute_by_id(dispute_id)
        if not dispute:
            await callback.answer("Спор не найден", show_alert=True)
            return
        deal_id = dispute.deal_id
        await state.update_data(dispute_id=dispute.id, deal_id=deal_id)
    deal = await deps.deal_service.get_deal(deal_id)
    if not deal:
        await callback.answer("Сделка не найдена", show_alert=True)
        return
    if action == "need:no":
        await state.update_data(seller_amount=Decimal("0"))
        await _show_dispute_close_summary(callback.message, state, deal, dispute_id)
        await callback.answer()
        return
    if action == "need:yes":
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="Да",
                callback_data=f"{DISPUTE_CLOSE_SELLER_PREFIX}full:yes",
            ),
            InlineKeyboardButton(
                text="Указать сумму",
                callback_data=f"{DISPUTE_CLOSE_SELLER_PREFIX}full:no",
            ),
        )
        await callback.message.answer(
            f"Всю сумму ({_format_decimal(deal.usdt_amount)} USDT) отправить продавцу?",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return
    if action == "full:yes":
        await state.update_data(seller_amount=deal.usdt_amount)
        await _show_dispute_close_summary(callback.message, state, deal, dispute_id)
        await callback.answer()
        return
    if action == "full:no":
        await state.set_state(DisputeAdminState.seller_amount)
        await callback.message.answer("Введи сумму USDT для продавца.")
        await callback.answer()


@router.message(DisputeAdminState.seller_amount)
async def dispute_seller_amount(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        amount = Decimal(text.replace(",", "."))
    except Exception:
        await message.answer("Не смог распознать число, попробуй снова.")
        return
    if amount < 0:
        await message.answer("Сумма не может быть отрицательной.")
        return
    deps = get_deps()
    data = await state.get_data()
    deal = await deps.deal_service.get_deal(data.get("deal_id", ""))
    if not deal:
        await state.clear()
        await message.answer("Сделка не найдена.")
        return
    buyer_amount = Decimal(str(data.get("buyer_amount", "0")))
    available = deal.usdt_amount - buyer_amount
    if amount > available:
        await message.answer(
            f"Сумма превышает доступный остаток ({_format_decimal(available)} USDT)."
        )
        return
    with suppress(TelegramBadRequest):
        await message.delete()
    await state.update_data(seller_amount=amount)
    await state.set_state(DisputeAdminState.confirm)
    await _refresh_dispute_admin_menu(message.bot, state)
    await message.answer(
        f"✅ Выплата продавцу установлена: {_format_decimal(amount)} USDT."
    )


@router.callback_query(F.data.startswith(DISPUTE_CLOSE_CONFIRM_PREFIX))
async def dispute_close_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or not await _has_dispute_access(user.id, deps):
        await callback.answer("Нет доступа", show_alert=True)
        return
    data = await state.get_data()
    payload = callback.data[len(DISPUTE_CLOSE_CONFIRM_PREFIX) :]
    dispute_id = None if payload in {"", "go"} else payload
    if not dispute_id:
        dispute_id = data.get("dispute_id")
    deal_id = data.get("deal_id")
    if not dispute_id:
        await callback.answer("Данные спора не найдены", show_alert=True)
        return
    if not deal_id:
        dispute = await deps.dispute_service.dispute_by_id(dispute_id)
        if not dispute:
            dispute = await deps.dispute_service.dispute_for_deal(dispute_id)
        if not dispute:
            await callback.answer("Спор не найден", show_alert=True)
            return
        deal_id = dispute.deal_id
    try:
        buyer_amount = Decimal(str(data.get("buyer_amount", "0")))
        seller_amount = Decimal(str(data.get("seller_amount", "0")))
    except Exception:
        await callback.answer("Некорректные суммы", show_alert=True)
        return
    deal = await deps.deal_service.get_deal(deal_id)
    if not deal:
        await callback.answer("Сделка не найдена", show_alert=True)
        return
    try:
        await deps.deal_service.resolve_dispute(
            deal_id,
            seller_amount=seller_amount,
            buyer_amount=buyer_amount,
        )
        await deps.dispute_service.resolve_dispute(
            dispute_id,
            resolved_by=user.id,
            seller_amount=str(seller_amount),
            buyer_amount=str(buyer_amount),
        )
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="К сделке", callback_data=f"{DEAL_INFO_PREFIX}{deal.id}")
    await callback.message.answer("Сделка закрыта по спору.")
    if deal.seller_id:
        if seller_amount > 0:
            seller_text = (
                f"✅ Спор по сделке {deal.hashtag} закрыт.\n"
                f"На баланс зачислено {_format_decimal(seller_amount)} USDT."
            )
        else:
            seller_text = (
                f"✅ Спор по сделке {deal.hashtag} закрыт.\n"
                "Сделка закрыта в пользу мерчанта."
            )
        await callback.bot.send_message(deal.seller_id, seller_text, reply_markup=builder.as_markup())
    if deal.buyer_id:
        if buyer_amount > 0:
            buyer_text = (
                f"✅ Спор по сделке {deal.hashtag} закрыт.\n"
                f"На баланс зачислено {_format_decimal(buyer_amount)} USDT."
            )
        else:
            buyer_text = (
                f"✅ Спор по сделке {deal.hashtag} закрыт.\n"
                "Сделка закрыта в пользу продавца."
            )
        await callback.bot.send_message(deal.buyer_id, buyer_text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith(DISPUTE_PAYOUT_PREFIX))
async def dispute_payout_edit(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or not await _has_dispute_access(user.id, deps):
        await callback.answer("Нет доступа", show_alert=True)
        return
    payload = callback.data[len(DISPUTE_PAYOUT_PREFIX) :]
    if payload == "buyer":
        await state.set_state(DisputeAdminState.buyer_amount)
        prompt = await callback.message.answer("Введи сумму USDT для мерчанта.")
        await state.update_data(dispute_payout_prompt_id=prompt.message_id)
        await callback.answer()
        return
    if payload == "seller":
        await state.set_state(DisputeAdminState.seller_amount)
        prompt = await callback.message.answer("Введи сумму USDT для продавца.")
        await state.update_data(dispute_payout_prompt_id=prompt.message_id)
        await callback.answer()
        return
    await callback.answer()


@router.callback_query(F.data.startswith(DISPUTE_TAKE_PREFIX))
async def dispute_take(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or not await _has_dispute_access(user.id, deps):
        await callback.answer("Нет доступа", show_alert=True)
        return
    dispute_id = callback.data[len(DISPUTE_TAKE_PREFIX) :]
    try:
        dispute = await deps.dispute_service.assign(dispute_id, user.id)
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    deal = await deps.deal_service.get_deal(dispute.deal_id)
    if not deal:
        await callback.answer("Сделка не найдена", show_alert=True)
        return
    seller_profile = await deps.user_service.profile_of(deal.seller_id)
    buyer_profile = await deps.user_service.profile_of(deal.buyer_id) if deal.buyer_id else None
    await state.clear()
    await state.update_data(
        dispute_id=dispute.id,
        deal_id=dispute.deal_id,
        buyer_amount=Decimal("0"),
        seller_amount=Decimal("0"),
    )
    text = _format_dispute_admin_card(
        deal, dispute, seller_profile, buyer_profile, Decimal("0"), Decimal("0")
    )
    markup = _dispute_admin_keyboard(dispute.id)
    sent = await callback.message.answer(text, reply_markup=markup)
    await state.update_data(
        dispute_menu_chat_id=sent.chat.id,
        dispute_menu_message_id=sent.message_id,
    )
    await callback.answer("Взято в работу")
@router.callback_query(F.data == ADMIN_RATE_SET)
async def admin_rate_set(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminRateState.waiting_rate)
    await callback.message.answer(
        "Введи новый курс (пример: 92.5). Для отмены напиши «Отмена».",
    )
    await callback.answer()


@router.callback_query(F.data == ADMIN_FEE_SET)
async def admin_fee_set(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="На вывод", callback_data=ADMIN_FEE_KIND_WITHDRAW),
        InlineKeyboardButton(text="На пополнение", callback_data=ADMIN_FEE_KIND_DEAL),
    )
    await callback.message.answer(
        "Какую комиссию хотите изменить?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.in_({ADMIN_FEE_KIND_WITHDRAW, ADMIN_FEE_KIND_DEAL}))
async def admin_fee_kind(callback: CallbackQuery, state: FSMContext) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    kind = "withdraw" if callback.data == ADMIN_FEE_KIND_WITHDRAW else "deal"
    await state.set_state(AdminRateState.waiting_fee)
    await state.update_data(fee_kind=kind)
    await callback.message.answer(
        "Введи новую комиссию в процентах (пример: 2.5). Для отмены напиши «Отмена».",
    )
    await callback.answer()


@router.callback_query(F.data == ADMIN_PANEL_MERCHANTS)
async def admin_panel_merchants(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await _send_merchants_list(callback.message.chat.id, callback.bot)
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_MERCHANT_VIEW_PREFIX))
async def admin_view_merchant(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    merchant_id = int(callback.data[len(ADMIN_MERCHANT_VIEW_PREFIX) :])
    await _send_merchant_detail(callback, merchant_id)
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_MERCHANT_DEALS_PREFIX))
async def admin_view_merchant_deals(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    merchant_id = int(callback.data[len(ADMIN_MERCHANT_DEALS_PREFIX) :])
    await _send_merchant_deals(callback, merchant_id, page=0)
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_MERCHANT_DEALS_PAGE_PREFIX))
async def admin_view_merchant_deals_page(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    payload = callback.data[len(ADMIN_MERCHANT_DEALS_PAGE_PREFIX) :]
    if ":" not in payload:
        await callback.answer("Некорректная страница.", show_alert=True)
        return
    merchant_id_str, page_str = payload.split(":", 1)
    if not merchant_id_str.isdigit() or not page_str.isdigit():
        await callback.answer("Некорректная страница.", show_alert=True)
        return
    await _send_merchant_deals(callback, int(merchant_id_str), page=int(page_str))
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_MERCHANT_DEAL_VIEW_PREFIX))
async def admin_view_merchant_deal_detail(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    payload = callback.data[len(ADMIN_MERCHANT_DEAL_VIEW_PREFIX) :]
    if ":" not in payload:
        await callback.answer()
        return
    merchant_id_str, deal_token = payload.split(":", 1)
    try:
        merchant_id = int(merchant_id_str)
    except ValueError:
        await callback.answer()
        return
    deal = await deps.deal_service.get_deal_by_token(deal_token)
    if not deal:
        await callback.answer("Сделка не найдена", show_alert=True)
        return
    seller_profile = await deps.user_service.profile_of(deal.seller_id)
    buyer_profile = await deps.user_service.profile_of(deal.buyer_id) if deal.buyer_id else None
    from cachebot.handlers.deal_flow import _format_deal_detail

    text = _format_deal_detail(
        deal,
        seller_profile,
        viewer_id=user.id,
        buyer_profile=buyer_profile,
        compact=False,
    )
    seller_username = _profile_username_label(seller_profile)
    buyer_username = _profile_username_label(buyer_profile) if buyer_profile else "—"
    text = f"{text}\n\nПродавец: {seller_username}\nПокупатель: {buyer_username}"
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_MERCHANT_EXCLUDE_PREFIX))
async def admin_exclude_merchant(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    merchant_id = int(callback.data[len(ADMIN_MERCHANT_EXCLUDE_PREFIX) :])
    await deps.user_service.set_role(merchant_id, UserRole.SELLER, revoke_merchant=True)
    with suppress(Exception):
        await callback.bot.send_message(
            merchant_id,
            "⚠️ Доступ покупателя отключен администратором.",
        )
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await callback.message.answer(
        f"Пользователь {merchant_id} исключён из списка мерчантов.",
        reply_markup=_admin_panel_back_markup(),
    )
    await callback.answer("Права мерчанта сняты")


@router.callback_query(F.data.startswith(APP_VIEW_PREFIX))
async def application_detail(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    app_id = callback.data[len(APP_VIEW_PREFIX) :]
    application = await deps.user_service.get_application(app_id)
    if not application:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    markup = None
    if application.status == ApplicationStatus.PENDING:
        builder = InlineKeyboardBuilder()
        builder.button(text="Принять", callback_data=f"{APP_ACCEPT_PREFIX}{application.id}")
        builder.button(text="Отклонить", callback_data=f"{APP_REJECT_PREFIX}{application.id}")
        builder.adjust(2)
        markup = builder.as_markup()
    summary = _format_application(application)
    if application.photo_file_ids:
        await callback.message.answer_photo(
            application.photo_file_ids[0],
            caption=summary,
            reply_markup=markup,
        )
    else:
        await callback.message.answer(summary, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith(APP_ACCEPT_PREFIX))
async def application_accept(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    app_id = callback.data[len(APP_ACCEPT_PREFIX) :]
    application = await deps.user_service.update_application_status(
        app_id, ApplicationStatus.ACCEPTED
    )
    if not application:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    await deps.user_service.set_role(application.user_id, UserRole.BUYER)
    await callback.message.answer(f"Заявка {application.id} одобрена. Права покупателя выданы.")
    try:
        await callback.bot.send_message(
            application.user_id,
            "✅ Твоя заявка мерчанта одобрена! Теперь доступен режим покупателя. "
            "Нажми /start, чтобы обновить меню.",
        )
    except Exception:
        pass
    await callback.answer("Заявка принята")


@router.callback_query(F.data.startswith(APP_REJECT_PREFIX))
async def application_reject(callback: CallbackQuery) -> None:
    deps = get_deps()
    user = callback.from_user
    if not user or user.id not in deps.config.admin_ids:
        await callback.answer("Нет доступа", show_alert=True)
        return
    app_id = callback.data[len(APP_REJECT_PREFIX) :]
    application = await deps.user_service.update_application_status(
        app_id, ApplicationStatus.REJECTED
    )
    if not application:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    await callback.message.answer(f"Заявка {application.id} отклонена.")
    try:
        await callback.bot.send_message(
            application.user_id,
            "К сожалению, твоя заявка мерчанта отклонена. "
            "Если хочешь попробовать снова, напиши /start позже.",
        )
    except Exception:
        pass
    await callback.answer("Заявка отклонена")


def _parse_rate_input(text: str) -> tuple[Decimal, Decimal | None]:
    normalized = text.replace(",", ".").split()
    if not normalized:
        raise ValueError("empty")
    usd_rate = Decimal(normalized[0])
    if usd_rate <= 0:
        raise ValueError("rate")
    fee_percent: Decimal | None = None
    if len(normalized) > 1:
        fee_percent = Decimal(normalized[1])
        if fee_percent < 0:
            raise ValueError("fee")
    return usd_rate, fee_percent


async def _apply_rate_change(
    deps, message: Message, usd_rate: Decimal, fee_percent: Decimal | None
) -> None:
    snapshot = await deps.rate_provider.set_rate(usd_rate, fee_percent)
    await message.answer(
        f"Новые параметры:\nКурс: 1 USDT = {_format_decimal(snapshot.usd_rate)} RUB\nКомиссия: {snapshot.fee_percent}%"
    )


async def _mark_deal_paid(deps, message: Message, deal_id: str) -> None:
    try:
        deal = await deps.deal_service.mark_paid_manual(deal_id)
    except Exception as exc:
        await message.answer(f"Не удалось отметить оплату: {exc}")
        return
    await message.answer(f"Сделка {deal.hashtag} отмечена как оплаченная")
    await message.bot.send_message(
        deal.seller_id,
        f"✅ Платеж по сделке {deal.hashtag} подтвержден вручную администратором.",
    )
    if deal.buyer_id:
        await message.bot.send_message(
            deal.buyer_id,
            f"Сделка {deal.hashtag} отмечена как оплаченная администратором. Ожидайте передачу наличных.",
        )


async def _send_balance(
    user_id: int,
    chat_id: int,
    bot,
    *,
    state: FSMContext | None = None,
) -> None:
    deps = get_deps()
    balance = await deps.deal_service.balance_of(user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬇️ Вывод", callback_data=BALANCE_WITHDRAW)
    builder.button(text="⬅️ Назад", callback_data=MenuAction.BACK.value)
    builder.adjust(1, 1)
    sent = await bot.send_message(
        chat_id,
        f"Твой баланс: {_format_decimal(balance)} USDT\n"
        f"Вывод доступен с комиссией {deps.config.withdraw_fee_percent}% "
        "(удерживается дополнительно).",
        reply_markup=builder.as_markup(),
    )
    if state:
        await state.update_data(last_menu_message_id=sent.message_id, last_menu_chat_id=sent.chat.id)


async def _send_profile(
    user,
    chat_id: int,
    bot,
    *,
    state: FSMContext | None = None,
) -> None:
    deps = get_deps()
    role = await deps.user_service.role_of(user.id)
    profile = await deps.user_service.ensure_profile(
        user.id,
        full_name=user.full_name,
        username=user.username,
    )
    deals = await deps.deal_service.list_user_deals(user.id)
    reviews = await deps.review_service.list_for_user(user.id)
    builder = InlineKeyboardBuilder()
    builder.button(text="Отзывы", callback_data=f"{REVIEWS_VIEW_PREFIX}{user.id}:pos")
    builder.button(text="⬅️ Назад", callback_data=MenuAction.BACK.value)
    builder.adjust(1, 1)
    sent = await bot.send_message(
        chat_id,
        _format_profile(
            profile,
            deals,
            review_summary=_review_summary_text(reviews),
            role=role,
            show_private=user.id in deps.config.admin_ids,
        ),
        reply_markup=builder.as_markup(),
    )
    if state:
        await state.update_data(last_menu_message_id=sent.message_id, last_menu_chat_id=sent.chat.id)


async def _render_my_deals(
    user_id: int,
    *,
    page: int,
    chat_id: int | None = None,
    bot=None,
    message: Message | None = None,
    state: FSMContext | None = None,
) -> None:
    deps = get_deps()
    deals = await deps.deal_service.list_user_deals(user_id)
    if not deals:
        text = "У тебя пока нет сделок"
        if message:
            with suppress(TelegramBadRequest):
                builder = InlineKeyboardBuilder()
                builder.button(text="⬅️ Назад", callback_data=MenuAction.BACK.value)
                await message.edit_text(text, reply_markup=builder.as_markup())
        elif bot and chat_id is not None:
            builder = InlineKeyboardBuilder()
            builder.button(text="⬅️ Назад", callback_data=MenuAction.BACK.value)
            sent = await bot.send_message(chat_id, text, reply_markup=builder.as_markup())
            if state:
                await state.update_data(
                    last_menu_message_id=sent.message_id,
                    last_menu_chat_id=sent.chat.id,
                )
        return
    total_pages = max(1, (len(deals) + DEALS_PER_PAGE - 1) // DEALS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * DEALS_PER_PAGE
    chunk = deals[start : start + DEALS_PER_PAGE]
    total = len(deals)
    success = sum(1 for item in deals if item.status == DealStatus.COMPLETED)
    failed = sum(1 for item in deals if item.status in {DealStatus.CANCELED, DealStatus.EXPIRED})
    text = _format_deal_list_text(
        total=total,
        success=success,
        failed=failed,
        page=page + 1,
        total_pages=total_pages,
    )
    markup = _build_my_deals_keyboard(chunk, page, total_pages, start_index=start, user_id=user_id)
    if message:
        with suppress(TelegramBadRequest):
            await message.edit_text(text, reply_markup=markup)
    elif bot and chat_id is not None:
        sent = await bot.send_message(chat_id, text, reply_markup=markup)
        if state:
            await state.update_data(
                last_menu_message_id=sent.message_id,
                last_menu_chat_id=sent.chat.id,
            )


async def _render_deal_detail(
    user_id: int,
    *,
    deal_id: str,
    page: int,
    message: Message | None = None,
) -> None:
    deps = get_deps()
    deal = await deps.deal_service.get_deal(deal_id)
    if not deal or user_id not in {deal.seller_id, deal.buyer_id}:
        if message:
            with suppress(TelegramBadRequest):
                await message.edit_text("Сделка недоступна или уже удалена.", reply_markup=None)
        return
    buyer_profile = None
    if deal.buyer_id:
        buyer_profile = await deps.user_service.profile_of(deal.buyer_id)
    seller_profile = await deps.user_service.profile_of(deal.seller_id)
    if message:
        bot = message.bot
        chat_id = message.chat.id
        with suppress(TelegramBadRequest):
            await message.delete()
        from cachebot.handlers.deal_flow import _send_deal_card  # reuse unified menu

        await _send_deal_card(
            bot=bot,
            chat_id=chat_id,
            deal=deal,
            viewer_id=user_id,
            seller_profile=seller_profile,
            buyer_profile=buyer_profile,
            back_page=page,
            cancel_page=page,
        )


def _build_my_deals_keyboard(
    deals: List[Deal],
    page: int,
    total_pages: int,
    *,
    start_index: int,
    user_id: int,
):
    builder = InlineKeyboardBuilder()
    for index, deal in enumerate(deals, start=start_index + 1):
        builder.row(
            InlineKeyboardButton(
                text=_deal_button_label(deal, user_id, index),
                callback_data=f"{MY_DEALS_VIEW_PREFIX}{page}:{deal.id}",
            )
        )
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text=f"Стр. {page}",
                    callback_data=f"{MY_DEALS_PAGE_PREFIX}{page - 1}",
                )
            )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text=f"Стр. {page + 2} ➡️",
                    callback_data=f"{MY_DEALS_PAGE_PREFIX}{page + 1}",
                )
            )
        if nav_buttons:
            builder.row(*nav_buttons)
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=MenuAction.BACK.value,
        )
    )
    return builder.as_markup()


def _build_deal_detail_keyboard(deal: Deal, page: int | None, user_id: int):
    builder = InlineKeyboardBuilder()
    if deal.buyer_id and user_id in {deal.seller_id, deal.buyer_id}:
        builder.row(
            InlineKeyboardButton(
                text="📨 Написать сообщение",
                callback_data=f"{MESSAGE_DEAL_PREFIX}{deal.id}",
            )
        )
    if user_id == deal.buyer_id:
        builder.row(
            InlineKeyboardButton(
                text="👤 Профиль продавца",
                callback_data=f"{PROFILE_VIEW_PREFIX}{deal.seller_id}",
            )
        )
    if user_id == deal.seller_id and deal.buyer_id:
        builder.row(
            InlineKeyboardButton(
                text="👤 Профиль покупателя",
                callback_data=f"{PROFILE_VIEW_PREFIX}{deal.buyer_id}",
            )
        )
    if deal.buyer_id and user_id == deal.buyer_id and deal.status in {DealStatus.RESERVED, DealStatus.PAID}:
        builder.row(
            InlineKeyboardButton(
                text="⛔️ Отменить",
                callback_data=f"{DEAL_CANCEL_PREFIX}{page}:{deal.id}",
            )
        )
    if user_id == deal.seller_id and deal.status == DealStatus.OPEN:
        builder.row(
            InlineKeyboardButton(
                text="⛔️ Отменить",
                callback_data=f"{DEAL_CANCEL_PREFIX}{page}:{deal.id}",
            )
        )
    if user_id == deal.seller_id and deal.status in {DealStatus.RESERVED, DealStatus.PAID}:
        if deal.status == DealStatus.PAID and deal.qr_stage == QrStage.READY and deal.qr_photo_id:
            pass
        else:
            builder.row(
                InlineKeyboardButton(
                    text="⛔️ Отменить",
                    callback_data=f"{DEAL_CANCEL_PREFIX}{page}:{deal.id}",
                )
            )

    qr_source = _encode_qr_source(page)
    if user_id == deal.buyer_id:
        if deal.status == DealStatus.PAID and deal.qr_stage in {QrStage.IDLE, QrStage.READY}:
            builder.row(
                InlineKeyboardButton(
                    text="📥 Запросить QR",
                    callback_data=_qr_request_payload(qr_source, deal.id),
                )
            )
        if deal.qr_photo_id:
            builder.row(
                InlineKeyboardButton(
                    text="👁 Посмотреть QR",
                    callback_data=_qr_view_payload(qr_source, deal.id),
                )
            )
        if deal.qr_stage == QrStage.READY and not deal.buyer_cash_confirmed:
            builder.row(
                InlineKeyboardButton(
                    text="✅ Успешно снял",
                    callback_data=_qr_buyer_done_payload(qr_source, deal.id),
                )
            )
    if user_id == deal.seller_id and deal.qr_stage in {
        QrStage.AWAITING_SELLER_ATTACH,
    }:
        builder.row(
            InlineKeyboardButton(
                text="✅ Готов отправить QR",
                callback_data=_qr_ready_payload(qr_source, deal.id),
            )
        )
    if user_id == deal.seller_id and deal.qr_stage == QrStage.AWAITING_SELLER_PHOTO:
        builder.row(
            InlineKeyboardButton(
                text="📎 Прикрепить QR",
                callback_data=_qr_attach_payload(qr_source, deal.id),
            )
        )
    if user_id == deal.seller_id and deal.qr_stage == QrStage.READY and not deal.seller_cash_confirmed:
        builder.row(
            InlineKeyboardButton(
                text="💸 Получил нал",
                callback_data=_qr_seller_done_payload(qr_source, deal.id),
            )
        )
    if (
        deal.status == DealStatus.PAID
        and user_id in {deal.seller_id, deal.buyer_id}
        and deal.dispute_opened_by is None
    ):
        builder.row(
            InlineKeyboardButton(
                text="🛡️ Открыть спор",
                callback_data=f"{DISPUTE_OPEN_PREFIX}{deal.id}",
            )
        )
    if (
        deal.status == DealStatus.DISPUTE
        and user_id == deal.buyer_id
        and deal.dispute_opened_by == deal.seller_id
    ):
        builder.row(
            InlineKeyboardButton(
                text="🧾 Дополнить спор",
                callback_data=f"{DISPUTE_APPEND_PREFIX}{deal.id}",
            )
        )

    return builder.as_markup()


def _deal_button_label(deal: Deal, user_id: int, index: int) -> str:
    role_icon = "💵" if deal.seller_id == user_id else "🛒"
    short_date = deal.created_at.strftime("%d.%m %H:%M")
    status_tag = _deal_stage_label(deal, user_id)
    return f"{role_icon} #{index} · {deal.hashtag} · {short_date} · {status_tag}"


def _qr_request_payload(source: str, deal_id: str) -> str:
    return f"{QR_REQUEST_PREFIX}{source}:{deal_id}"


def _qr_view_payload(source: str, deal_id: str) -> str:
    return f"{QR_VIEW_PREFIX}{source}:{deal_id}"


def _qr_attach_payload(source: str, deal_id: str) -> str:
    return f"{QR_SELLER_ATTACH_PREFIX}{source}:{deal_id}"


def _qr_ready_payload(source: str, deal_id: str) -> str:
    return f"{QR_SELLER_READY_PREFIX}{source}:{deal_id}"


def _qr_buyer_done_payload(source: str, deal_id: str) -> str:
    return f"{QR_BUYER_DONE_PREFIX}{source}:{deal_id}"


def _qr_seller_done_payload(source: str, deal_id: str) -> str:
    return f"{QR_SELLER_DONE_PREFIX}{source}:{deal_id}"


def _seller_cash_confirm_keyboard(step: int, source: str, deal_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if step == 1:
        builder.button(
            text="Да",
            callback_data=f"{QR_SELLER_CONFIRM_STEP1_PREFIX}{source}:{deal_id}:yes",
        )
        builder.button(
            text="Отмена",
            callback_data=f"{QR_SELLER_CONFIRM_STEP1_PREFIX}{source}:{deal_id}:no",
        )
    else:
        builder.button(
            text="Подтверждаю",
            callback_data=f"{QR_SELLER_CONFIRM_STEP2_PREFIX}{source}:{deal_id}:yes",
        )
        builder.button(
            text="Отмена",
            callback_data=f"{QR_SELLER_CONFIRM_STEP2_PREFIX}{source}:{deal_id}:no",
        )
    builder.adjust(1)
    return builder.as_markup()


def _encode_qr_source(page: int | str) -> str:
    if isinstance(page, int):
        return f"list-{page}"
    return str(page)


def _decode_qr_source(raw: str) -> tuple[str, int | None]:
    if raw.startswith("list-"):
        try:
            return "list", int(raw.split("-", 1)[1])
        except ValueError:
            return "list", None
    return raw, None


def _format_deal_list_text(
    *,
    total: int,
    success: int,
    failed: int,
    page: int,
    total_pages: int,
) -> str:
    lines = [
        "<b>📂 Мои сделки</b>",
        f"Всего: {total}",
        f"Успешных: {success}",
        f"Отменённых/истёкших: {failed}",
        f"Страница {page}/{total_pages}",
    ]
    lines.append("")
    lines.append("Выбери сделку кнопками ниже.")
    return "\n".join(lines)


def _format_deal_detail(deal: Deal, user_id: int, buyer_profile: UserProfile | None = None) -> str:
    role = "Продавец" if deal.seller_id == user_id else "Покупатель"
    created = deal.created_at.astimezone(timezone.utc).strftime("%d.%m %H:%M")
    atm = bank_label(deal.atm_bank)
    status_text = _deal_stage_label(deal, user_id)
    buyer_label = "Покупатель" if deal.is_p2p else "Мерчант"
    lines = [
        f"<b>Сделка {deal.hashtag}</b>",
        f"Роль: {role}",
        f"Статус: <b>{status_text}</b>",
        f"Наличные: ₽{_format_decimal(deal.usd_amount)} RUB",
        f"USDT к оплате: {_format_decimal(deal.usdt_amount)}",
        f"Создано: {created}",
        f"Банкомат: {atm}",
    ]
    if deal.buyer_id:
        buyer_name = _format_buyer_name(buyer_profile, deal.buyer_id)
        lines.append(f"{buyer_label}: {buyer_name}")
    else:
        lines.append(f"{buyer_label}: —")
    if deal.comment:
        lines.append(f"Комментарий: {escape(deal.comment)}")
    return "\n".join(lines)


async def _handle_deal_completed(deal: Deal, deps, bot) -> None:
    await deps.dispute_service.resolve_for_deal(deal.id, resolved_by=0)
    if deal.buyer_id:
        kb_configured = bool(deps.config.kb_api_url and deps.config.kb_api_token)
        credited = True
        if kb_configured:
            credited = await deps.kb_client.credit_balance(deal.buyer_id, deal.usdt_amount)
        buyer_note = (
            f"Средства зачислены на баланс ({_format_decimal(deal.usdt_amount)} USDT)."
            if credited or not kb_configured
            else "Не удалось обновить баланс автоматически, обратитесь к админу."
        )
        buyer_review = await deps.review_service.review_for_deal(
            deal.id, prefer_from=deal.buyer_id
        )
        buyer_builder = InlineKeyboardBuilder()
        if buyer_review is None:
            buyer_builder.button(
                text="Оценить сделку",
                callback_data=f"{REVIEW_START_PREFIX}{deal.id}",
            )
        await bot.send_message(
            deal.buyer_id,
            f"✅ Сделка {deal.hashtag} завершена.\n{buyer_note}\n"
            "Используй кнопку «Баланс», чтобы оформить вывод USDT.",
            reply_markup=buyer_builder.as_markup() if buyer_review is None else None,
        )
    if deal.seller_id:
        review = await deps.review_service.review_for_deal(
            deal.id, prefer_from=deal.seller_id
        )
        builder = InlineKeyboardBuilder()
        if review is None:
            builder.button(
                text="Оценить сделку",
                callback_data=f"{REVIEW_START_PREFIX}{deal.id}",
            )
        await bot.send_message(
            deal.seller_id,
            f"✅ Сделка {deal.hashtag} выполнена. Спасибо за использование сервиса.",
            reply_markup=builder.as_markup() if review is None else None,
        )


@router.message(SellerQrUploadState.waiting_photo)
async def seller_qr_photo(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        await message.answer("Не удалось определить отправителя.")
        return
    data = await state.get_data()
    deal_id = data.get("qr_deal_id")
    if not deal_id:
        await state.clear()
        await message.answer("Не удалось найти сделку, начните заново.")
        return
    if not message.photo:
        await message.answer("Прикрепи фотографию QR-кода.")
        return
    file_id = message.photo[-1].file_id
    deps = get_deps()
    try:
        deal = await deps.deal_service.attach_qr_photo(deal_id, message.from_user.id, file_id)
    except Exception as exc:
        await message.answer(f"Не удалось сохранить QR: {exc}")
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="К сделке", callback_data=f"{DEAL_INFO_PREFIX}{deal.id}")
    await message.answer("QR отправлен покупателю.", reply_markup=builder.as_markup())
    await state.clear()
    if deal.buyer_id:
        builder = InlineKeyboardBuilder()
        builder.button(
            text="👁 Посмотреть QR",
            callback_data=f"{QR_VIEW_PREFIX}info:{deal.id}",
        )
        builder.button(
            text="К сделке",
            callback_data=f"{DEAL_INFO_PREFIX}{deal.id}",
        )
        builder.adjust(1)
        await message.bot.send_message(
            deal.buyer_id,
            f"Продавец прикрепил новый QR по сделке {deal.hashtag}.",
            reply_markup=builder.as_markup(),
        )


@router.message(WithdrawState.waiting_amount)
async def balance_withdraw_amount(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if not user:
        return
    text = (message.text or "").strip()
    if text.lower() == "отмена":
        await state.clear()
        await message.answer("Вывод отменен.")
        return
    try:
        amount = Decimal(text.replace(",", "."))
    except Exception:
        await message.answer("Не удалось распознать число, попробуй еще раз.")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше нуля.")
        return
    deps = get_deps()
    fee_percent = deps.config.withdraw_fee_percent
    fee = (amount * fee_percent / Decimal("100")).quantize(Decimal("0.00000001"))
    total = (amount + fee).quantize(Decimal("0.00000001"))
    balance = await deps.deal_service.balance_of(user.id)
    if balance < total:
        await message.answer(
            f"Недостаточно средств. Доступно {_format_decimal(balance)} USDT с учетом комиссии."
        )
        return
    try:
        await deps.deal_service.withdraw_balance(user.id, total)
    except Exception as exc:
        await message.answer(f"Не удалось списать средства: {exc}")
        return
    try:
        await deps.crypto_pay.transfer(user_id=user.id, amount=amount, currency="USDT")
    except Exception as exc:
        await deps.deal_service.deposit_balance(user.id, total)
        await message.answer(f"Перевод не выполнен: {exc}")
        return
    await state.clear()
    await message.answer(
        "Заявка на вывод выполнена.\n"
        f"Получатель: @{user.username or user.id}\n"
        f"Сумма: {_format_decimal(amount)} USDT\n"
        f"Комиссия: {_format_decimal(fee)} USDT\n"
        f"Списано: {_format_decimal(total)} USDT\n"
        "Отправлено в Crypto Bot."
    )


def _format_profile(
    profile: UserProfile,
    deals: List[Deal],
    *,
    review_summary: str,
    role: UserRole | None = None,
    show_private: bool = False,
) -> str:
    total = len(deals)
    success = sum(1 for deal in deals if deal.status == DealStatus.COMPLETED)
    failed = sum(
        1 for deal in deals if deal.status in {DealStatus.CANCELED, DealStatus.EXPIRED}
    )
    display_name = getattr(profile, "display_name", None) or profile.full_name or "—"
    name = escape(display_name)
    registered = profile.registered_at.astimezone(timezone.utc).strftime(
        "%d.%m.%Y %H:%M UTC"
    )
    role_line = "Роль: Мерчант" if role == UserRole.BUYER else None
    private_lines = []
    if show_private:
        real_name = escape(profile.full_name) if profile.full_name else "—"
        username = escape(profile.username) if profile.username else "—"
        private_lines = [f"Telegram имя: {real_name}", f"Username: @{username}"]
    lines = [
        "<b>👤 Мой профиль</b>",
        "──────────────",
        f"Имя: {name}",
        *([role_line] if role_line else []),
        *private_lines,
        f"Дата регистрации: {registered}",
        "",
        f"Сделок всего: {total}",
        f"Успешных: {success} ({_percent(success, total)})",
        f"Неуспешных: {failed} ({_percent(failed, total)})",
        review_summary,
    ]
    return "\n".join(lines)


def _reviews_keyboard(user_id: int, kind: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    pos_prefix = "✅ " if kind == "pos" else ""
    neg_prefix = "✅ " if kind == "neg" else ""
    builder.button(
        text=f"{pos_prefix}👍 Положительные",
        callback_data=f"{REVIEWS_VIEW_PREFIX}{user_id}:pos",
    )
    builder.button(
        text=f"{neg_prefix}👎 Отрицательные",
        callback_data=f"{REVIEWS_VIEW_PREFIX}{user_id}:neg",
    )
    builder.adjust(1)
    return builder.as_markup()


async def _format_reviews_list(
    user_id: int,
    reviews: List[Review],
    kind: str,
    deps,
) -> str:
    is_positive = kind != "neg"
    filtered = [review for review in reviews if (review.rating > 0) == is_positive]
    title = "Положительные отзывы" if is_positive else "Отрицательные отзывы"
    lines = [f"<b>📌 {title}</b>"]
    if not filtered:
        lines.append("Пока нет отзывов.")
        return "\n".join(lines)
    for index, review in enumerate(filtered[:20], start=1):
        profile = await deps.user_service.profile_of(review.from_user_id)
        author = "—"
        if profile:
            author = profile.full_name or profile.username or "—"
        mark = "👍" if review.rating > 0 else "👎"
        comment = review.comment or "Без комментария"
        created = review.created_at.astimezone(timezone.utc).strftime("%d.%m %H:%M")
        lines.append(f"{index}. {mark} {escape(author)} — {escape(comment)} ({created})")
    if len(filtered) > 20:
        lines.append(f"Показаны последние 20 из {len(filtered)}.")
    return "\n".join(lines)


def _percent(part: int, total: int) -> str:
    if total == 0:
        return "0%"
    value = round(part * 100 / total, 1)
    return f"{value}%"


def _review_summary_text(reviews: List[Review]) -> str:
    total = len(reviews)
    if total == 0:
        return "Отзывы: 0% (пока нет отзывов)"
    positive = sum(1 for review in reviews if review.rating > 0)
    negative = sum(1 for review in reviews if review.rating < 0)
    percent = round(positive * 100 / total, 1)
    return f"Отзывы: {percent}% (👍 {positive} / 👎 {negative})"


async def _send_disputes_list(chat_id: int, bot) -> None:
    deps = get_deps()
    viewer_id = chat_id
    disputes = await deps.dispute_service.list_open_disputes_for(viewer_id)
    if not disputes:
        await bot.send_message(chat_id, "Открытых споров нет.")
        return
    now = datetime.now(timezone.utc)

    def urgency_bucket(dispute) -> int:
        age = now - dispute.opened_at
        minutes = age.total_seconds() / 60
        if minutes > 120:
            return 0  # red
        if minutes > 30:
            return 1  # yellow
        return 2  # green

    disputes.sort(
        key=lambda item: (
            0 if viewer_id and item.assigned_to == viewer_id else 1,
            urgency_bucket(item),
            -item.opened_at.timestamp(),
        )
    )
    builder = InlineKeyboardBuilder()
    for item in disputes:
        deal = await deps.deal_service.get_deal(item.deal_id)
        if not deal:
            continue
        label = _dispute_button_label(deal, item, now=now, viewer_id=viewer_id)
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=f"{DISPUTE_VIEW_PREFIX}{item.id}",
            )
        )
    await bot.send_message(
        chat_id,
        f"Открытых споров: {len(disputes)}",
        reply_markup=builder.as_markup(),
    )


def _dispute_button_label(
    deal: Deal,
    dispute,
    *,
    now: datetime | None = None,
    viewer_id: int | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    age_minutes = (now - dispute.opened_at).total_seconds() / 60
    if viewer_id and dispute.assigned_to == viewer_id:
        emoji = "⏳"
    elif age_minutes > 120:
        emoji = "🔴"
    elif age_minutes > 30:
        emoji = "🟡"
    else:
        emoji = "🟢"
    created = dispute.opened_at.astimezone(timezone.utc).strftime("%d.%m %H:%M")
    amount = _format_decimal(deal.usd_amount)
    return f"{emoji} ₽{amount} • {created}"


def _dispute_detail_keyboard(dispute_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Доказательства",
            callback_data=f"{DISPUTE_EVIDENCE_VIEW_PREFIX}{dispute_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="Закрыть сделку",
            callback_data=f"{DISPUTE_CLOSE_PREFIX}{dispute_id}",
        )
    )
    return builder.as_markup()


def _dispute_admin_keyboard(dispute_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📎 Доказательства продавца",
            callback_data=f"{DISPUTE_EVIDENCE_VIEW_PREFIX}seller",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📎 Доказательства мерчанта",
            callback_data=f"{DISPUTE_EVIDENCE_VIEW_PREFIX}buyer",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✏️ Выплата мерчанту",
            callback_data=f"{DISPUTE_PAYOUT_PREFIX}buyer",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✏️ Выплата продавцу",
            callback_data=f"{DISPUTE_PAYOUT_PREFIX}seller",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✅ Завершить спор",
            callback_data=f"{DISPUTE_CLOSE_CONFIRM_PREFIX}go",
        )
    )
    return builder.as_markup()


def _pick_latest_comment(items: list[str]) -> str:
    for text in reversed(items):
        if text:
            return text
    return "—"


def _format_dispute_admin_card(
    deal: Deal,
    dispute,
    seller_profile: UserProfile | None,
    buyer_profile: UserProfile | None,
    buyer_amount: Decimal,
    seller_amount: Decimal,
) -> str:
    seller_name = seller_profile.full_name if seller_profile else "—"
    buyer_name = buyer_profile.full_name if buyer_profile else "—"
    opened_at = dispute.opened_at.astimezone(timezone.utc).strftime("%d.%m %H:%M")
    opener_label = "Продавец" if dispute.opened_by == deal.seller_id else "Мерчант"
    seller_comments = []
    buyer_comments = []
    if dispute.comment:
        if dispute.opened_by == deal.seller_id:
            seller_comments.append(dispute.comment)
        elif deal.buyer_id:
            buyer_comments.append(dispute.comment)
    for item in dispute.messages:
        if item.author_id == deal.seller_id:
            seller_comments.append(item.text)
        elif deal.buyer_id and item.author_id == deal.buyer_id:
            buyer_comments.append(item.text)
    seller_comment = _pick_latest_comment(seller_comments)
    buyer_comment = _pick_latest_comment(buyer_comments)
    seller_evidence = sum(1 for item in dispute.evidence if item.author_id == deal.seller_id)
    buyer_evidence = sum(
        1 for item in dispute.evidence if deal.buyer_id and item.author_id == deal.buyer_id
    )
    total_paid = deal.usdt_amount
    remainder = total_paid - buyer_amount - seller_amount
    lines = [
        f"<b>🛡️ Спор по сделке {deal.hashtag}</b>",
        f"💵 Наличные: {_format_decimal(deal.usd_amount)} RUB",
        f"🪙 USDT к оплате: {_format_decimal(deal.usdt_amount)}",
        f"✅ Оплачено продавцом: {_format_decimal(total_paid)} USDT",
        f"🕒 Открыт: {opened_at}",
        f"🧾 Открыл: {opener_label}",
        "",
        f"👤 Продавец: {escape(seller_name)}",
        f"Комментарий продавца: {escape(seller_comment)}",
        f"Доказательств продавца: {seller_evidence}",
        "",
        f"👔 Мерчант: {escape(buyer_name)}",
        f"Комментарий мерчанта: {escape(buyer_comment)}",
        f"Доказательств мерчанта: {buyer_evidence}",
        "",
        f"Доступно к выдаче: {_format_decimal(remainder)} USDT",
        "<b>План выплат</b>",
        f"Мерчант: {_format_decimal(buyer_amount)} USDT",
        f"Продавец: {_format_decimal(seller_amount)} USDT",
    ]
    if remainder < 0:
        lines.append(f"⚠️ Превышение: {_format_decimal(-remainder)} USDT")
    return "\n".join(lines)


async def _refresh_dispute_admin_menu(bot, state: FSMContext) -> None:
    deps = get_deps()
    data = await state.get_data()
    dispute_id = data.get("dispute_id")
    deal_id = data.get("deal_id")
    if not dispute_id or not deal_id:
        return
    dispute = await deps.dispute_service.dispute_by_id(dispute_id)
    deal = await deps.deal_service.get_deal(deal_id)
    if not dispute or not deal:
        return
    buyer_profile = await deps.user_service.profile_of(deal.buyer_id) if deal.buyer_id else None
    seller_profile = await deps.user_service.profile_of(deal.seller_id)
    buyer_amount = Decimal(str(data.get("buyer_amount", "0")))
    seller_amount = Decimal(str(data.get("seller_amount", "0")))
    text = _format_dispute_admin_card(
        deal, dispute, seller_profile, buyer_profile, buyer_amount, seller_amount
    )
    markup = _dispute_admin_keyboard(dispute.id)
    chat_id = data.get("dispute_menu_chat_id")
    message_id = data.get("dispute_menu_message_id")
    if chat_id and message_id:
        with suppress(TelegramBadRequest):
            await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
            )


def _format_dispute_detail(deal: Deal, dispute, seller_profile, buyer_profile) -> str:
    seller_name = seller_profile.full_name if seller_profile else "—"
    seller_username = f"@{seller_profile.username}" if seller_profile and seller_profile.username else "—"
    buyer_name = buyer_profile.full_name if buyer_profile else "—"
    buyer_username = f"@{buyer_profile.username}" if buyer_profile and buyer_profile.username else "—"
    opened_at = dispute.opened_at.astimezone(timezone.utc).strftime("%d.%m %H:%M")
    lines = [
        f"<b>Спор по сделке {deal.hashtag}</b>",
        f"Сумма: {_format_decimal(deal.usd_amount)} RUB",
        f"USDT: {_format_decimal(deal.usdt_amount)}",
        f"Открыт: {opened_at}",
        "",
        f"Продавец: {escape(seller_name)} ({escape(seller_username)})",
        f"Мерчант: {escape(buyer_name)} ({escape(buyer_username)})",
        "",
        f"Причина: {escape(dispute.reason)}",
    ]
    if dispute.comment:
        lines.append(f"Комментарий: {escape(dispute.comment)}")
    lines.append(f"Доказательств: {len(dispute.evidence)}")
    return "\n".join(lines)


async def _format_dispute_messages(dispute, deps) -> str:
    if not dispute.messages:
        return "Сообщений нет."
    lines = ["<b>Сообщения</b>"]
    for index, item in enumerate(dispute.messages[-10:], start=1):
        profile = await deps.user_service.profile_of(item.author_id)
        name = "—"
        if profile:
            name = profile.full_name or profile.username or "—"
        created = item.created_at.astimezone(timezone.utc).strftime("%d.%m %H:%M")
        lines.append(f"{index}. {escape(name)}: {escape(item.text)} ({created})")
    if len(dispute.messages) > 10:
        lines.append(f"Показаны последние 10 из {len(dispute.messages)}.")
    return "\n".join(lines)


async def _dispute_author_label(author_id: int, deal: Deal | None, deps) -> tuple[str, str]:
    profile = await deps.user_service.profile_of(author_id)
    name = "—"
    if profile:
        name = profile.full_name or profile.username or "—"
    role = "Мерчант"
    if deal and author_id == deal.seller_id:
        role = "Продавец"
    elif deal and author_id == deal.buyer_id:
        role = "Мерчант"
    return name, role


async def _ask_seller_payout(
    callback: CallbackQuery, state: FSMContext, dispute_id: str
) -> None:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Да",
            callback_data=f"{DISPUTE_CLOSE_SELLER_PREFIX}need:yes",
        ),
        InlineKeyboardButton(
            text="Нет",
            callback_data=f"{DISPUTE_CLOSE_SELLER_PREFIX}need:no",
        ),
    )
    await callback.message.answer("Нужно ли отправить USDT продавцу?", reply_markup=builder.as_markup())


async def _ask_seller_payout_message(
    message: Message, state: FSMContext, dispute_id: str
) -> None:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Да",
            callback_data=f"{DISPUTE_CLOSE_SELLER_PREFIX}need:yes",
        ),
        InlineKeyboardButton(
            text="Нет",
            callback_data=f"{DISPUTE_CLOSE_SELLER_PREFIX}need:no",
        ),
    )
    await message.answer("Нужно ли отправить USDT продавцу?", reply_markup=builder.as_markup())


async def _show_dispute_close_summary(
    message: Message, state: FSMContext, deal: Deal, dispute_id: str
) -> None:
    data = await state.get_data()
    buyer_amount = Decimal(str(data.get("buyer_amount", "0")))
    seller_amount = Decimal(str(data.get("seller_amount", "0")))
    winner = data.get("winner_side")
    winner_label = "Мерчант" if winner == "buyer" else "Продавец"
    summary = (
        "<b>Итоговые значения</b>\n"
        f"Победитель: {winner_label}\n"
        f"Мерчант: {_format_decimal(buyer_amount)} USDT\n"
        f"Продавец: {_format_decimal(seller_amount)} USDT"
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Завершить сделку",
            callback_data=f"{DISPUTE_CLOSE_CONFIRM_PREFIX}go",
        )
    )
    builder.row(
        InlineKeyboardButton(text="Отмена", callback_data=DISPUTE_LIST_PREFIX)
    )
    if isinstance(message, CallbackQuery):
        await message.message.answer(summary, reply_markup=builder.as_markup())
    else:
        await message.answer(summary, reply_markup=builder.as_markup())


async def _finalize_review(user, event, state: FSMContext, *, comment: str | None) -> None:
    if not user:
        return
    data = await state.get_data()
    deal_id = data.get("review_deal_id")
    rating = data.get("review_rating")
    target_id = data.get("review_target_id")
    if not deal_id or rating is None or not target_id:
        await state.clear()
        if isinstance(event, CallbackQuery):
            await event.answer("Не удалось сохранить отзыв", show_alert=True)
        else:
            await event.answer("Не удалось сохранить отзыв")
        return
    deps = get_deps()
    try:
        await deps.review_service.add_review(
            deal_id=deal_id,
            from_user_id=user.id,
            to_user_id=int(target_id),
            rating=int(rating),
            comment=comment,
        )
    except Exception as exc:
        await state.clear()
        if isinstance(event, CallbackQuery):
            await event.answer(str(exc), show_alert=True)
        else:
            await event.answer(f"Не удалось сохранить отзыв: {exc}")
        return
    await state.clear()
    if isinstance(event, CallbackQuery):
        with suppress(TelegramBadRequest):
            await event.message.delete()
        await event.bot.send_message(event.message.chat.id, "Спасибо за отзыв!")
        bot = event.bot
        chat_id = event.message.chat.id
    else:
        await event.answer("Спасибо за отзыв!")
        bot = event.bot
        chat_id = event.chat.id
    deal = await deps.deal_service.get_deal(deal_id)
    if not deal:
        return
    buyer_profile = None
    if deal.buyer_id:
        buyer_profile = await deps.user_service.profile_of(deal.buyer_id)
    seller_profile = await deps.user_service.profile_of(deal.seller_id)
    from cachebot.handlers.deal_flow import _send_deal_card

    await _send_deal_card(
        bot=bot,
        chat_id=chat_id,
        deal=deal,
        viewer_id=user.id,
        seller_profile=seller_profile,
        buyer_profile=buyer_profile,
        back_page=None,
    )


def _deal_stage_label(deal: Deal, viewer_id: int) -> str:
    if deal.status == DealStatus.OPEN:
        if viewer_id == deal.seller_id:
            return "Ожидаем покупателя" if deal.is_p2p else "Ожидаем Мерчанта"
        return "Ждем оплату"
    if deal.status == DealStatus.RESERVED:
        return "Ждем оплату"
    if deal.status == DealStatus.PAID:
        if deal.qr_stage == QrStage.READY and deal.qr_photo_id:
            return "Выдача наличных"
        if deal.qr_stage == QrStage.AWAITING_SELLER_ATTACH:
            return "Подготовка QR"
        if deal.qr_stage == QrStage.AWAITING_BUYER_READY:
            return "Ожидаем готовность"
        if deal.qr_stage == QrStage.AWAITING_SELLER_PHOTO:
            return "Прикрепление QR"
        return "Отправка QR"
    if deal.status == DealStatus.DISPUTE:
        return "Открыт спор"
    if deal.status == DealStatus.COMPLETED:
        return "Завершена"
    if deal.status == DealStatus.CANCELED:
        return "Отменена"
    if deal.status == DealStatus.EXPIRED:
        return "Истекла"
    return deal.status.value


def _format_buyer_name(profile: UserProfile | None, fallback_id: int) -> str:
    if profile:
        if getattr(profile, "display_name", None):
            return profile.display_name
        if profile.full_name:
            return profile.full_name
        if profile.username:
            return profile.username
    return "—"


async def _cancel_deal_core(user_id: int, deal_id: str) -> tuple[Deal, Decimal | None]:
    deps = get_deps()
    return await deps.deal_service.cancel_deal(deal_id, user_id)


async def _complete_deal_core(user_id: int, deal_id: str, bot) -> Deal:
    deps = get_deps()
    deal, payout = await deps.deal_service.complete_deal(deal_id, user_id)
    if payout:
        await _handle_deal_completed(deal, deps, bot)
    elif deal.buyer_id:
        await bot.send_message(deal.buyer_id, f"Сделка {deal.hashtag} закрыта продавцом")
    return deal


async def _delete_callback_message(callback: CallbackQuery) -> None:
    message = callback.message
    if not message:
        return
    with suppress(TelegramBadRequest):
        await message.delete()


async def _send_admin_panel(chat_id: int, bot) -> None:
    builder = InlineKeyboardBuilder()
    builder.button(text="👔 Мерчанты", callback_data=ADMIN_PANEL_MERCHANTS)
    builder.button(text="📥 Заявки", callback_data=ADMIN_PANEL_APPS)
    builder.button(text="👥 Модераторы", callback_data=ADMIN_PANEL_MODERATORS)
    builder.button(text="Управление", callback_data=ADMIN_PANEL_RATES)
    builder.adjust(1)
    await bot.send_message(
        chat_id,
        "Выбери раздел админ-панели:",
        reply_markup=builder.as_markup(),
    )


async def _send_moderators_list(chat_id: int, bot) -> None:
    deps = get_deps()
    moderators = await deps.user_service.list_moderators()
    if not moderators:
        await bot.send_message(
            chat_id,
            "Модераторов пока нет.",
            reply_markup=_admin_panel_back_markup(),
        )
        return
    builder = InlineKeyboardBuilder()
    for moderator_id in moderators:
        profile = await deps.user_service.profile_of(moderator_id)
        if profile and profile.username:
            label = f"@{profile.username}"
        else:
            label = str(moderator_id)
        builder.button(text=label, callback_data=f"{ADMIN_MODERATOR_VIEW_PREFIX}{moderator_id}")
    builder.adjust(1)
    await bot.send_message(
        chat_id,
        "Выбери модератора:",
        reply_markup=builder.as_markup(),
    )


async def _send_moderator_disputes(chat_id: int, bot, moderator_id: int) -> None:
    deps = get_deps()
    disputes = await deps.dispute_service.list_assigned_open(moderator_id)
    if not disputes:
        await bot.send_message(chat_id, "Споров в работе нет.")
        return
    now = datetime.now(timezone.utc)
    disputes.sort(key=lambda item: -item.opened_at.timestamp())
    builder = InlineKeyboardBuilder()
    for item in disputes:
        deal = await deps.deal_service.get_deal(item.deal_id)
        if not deal:
            continue
        label = _dispute_button_label(deal, item, now=now, viewer_id=moderator_id)
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=f"{DISPUTE_VIEW_PREFIX}{item.id}",
            )
        )
    await bot.send_message(
        chat_id,
        "Споры модератора:",
        reply_markup=builder.as_markup(),
    )


async def _send_applications_list(chat_id: int, bot) -> None:
    deps = get_deps()
    applications = await deps.user_service.list_applications()
    if not applications:
        await bot.send_message(
            chat_id,
            "Заявок пока нет",
            reply_markup=_admin_panel_back_markup(),
        )
        return
    keyboard = InlineKeyboardBuilder()
    for app in applications:
        label = f"@{app.username}" if app.username else str(app.user_id)
        keyboard.button(text=label, callback_data=f"{APP_VIEW_PREFIX}{app.id}")
    keyboard.adjust(1)
    await bot.send_message(
        chat_id,
        "Выбери заявку для просмотра:",
        reply_markup=keyboard.as_markup(),
    )


async def _notify_seller_qr_request(deal: Deal, banks: List[str], bot) -> None:
    builder = InlineKeyboardBuilder()
    for bank in banks:
        builder.button(
            text=bank_label(bank),
            callback_data=f"{QR_SELLER_BANK_PREFIX}{deal.id}:{bank}",
        )
    builder.adjust(1)
    await bot.send_message(
        deal.seller_id,
        f"Покупатель запросил банкомат по сделке {deal.hashtag}.\nВыбери банк, который сможешь обработать.",
        reply_markup=builder.as_markup(),
    )


async def _send_merchants_list(chat_id: int, bot) -> None:
    deps = get_deps()
    merchants = await deps.user_service.list_merchants()
    if not merchants:
        await bot.send_message(
            chat_id,
            "Мерчантов пока нет",
            reply_markup=_admin_panel_back_markup(),
        )
        return
    builder = InlineKeyboardBuilder()
    for record in merchants:
        builder.button(
            text=_merchant_button_label(record),
            callback_data=f"{ADMIN_MERCHANT_VIEW_PREFIX}{record.user_id}",
        )
    builder.adjust(1)
    await bot.send_message(
        chat_id,
        "Выбери мерчанта:",
        reply_markup=builder.as_markup(),
    )


async def _send_merchant_detail(callback: CallbackQuery, merchant_id: int) -> None:
    deps = get_deps()
    profile = await deps.user_service.profile_of(merchant_id)
    since = await deps.user_service.merchant_since_of(merchant_id)
    deals = await deps.deal_service.list_user_deals(merchant_id)
    text = _format_merchant_summary(merchant_id, profile, since, deals)
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📂 Сделки",
        callback_data=f"{ADMIN_MERCHANT_DEALS_PREFIX}{merchant_id}",
    )
    builder.button(
        text="🚫 Исключить",
        callback_data=f"{ADMIN_MERCHANT_EXCLUDE_PREFIX}{merchant_id}",
    )
    builder.adjust(1)
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await callback.bot.send_message(
        callback.message.chat.id,
        text,
        reply_markup=builder.as_markup(),
    )


async def _send_merchant_deals(callback: CallbackQuery, merchant_id: int, *, page: int) -> None:
    deps = get_deps()
    deals = await deps.deal_service.list_user_deals(merchant_id)
    builder = InlineKeyboardBuilder()
    total_pages = max(1, (len(deals) + ADMIN_DEALS_PER_PAGE - 1) // ADMIN_DEALS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * ADMIN_DEALS_PER_PAGE
    chunk = deals[start : start + ADMIN_DEALS_PER_PAGE]
    for deal in chunk:
        builder.row(
            InlineKeyboardButton(
                text=_admin_deal_button_label(deal),
                callback_data=f"{ADMIN_MERCHANT_DEAL_VIEW_PREFIX}{merchant_id}:{deal.public_id}",
            )
        )
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text=f"Стр. {page}",
                    callback_data=f"{ADMIN_MERCHANT_DEALS_PAGE_PREFIX}{merchant_id}:{page - 1}",
                )
            )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text=f"Стр. {page + 2} ➡️",
                    callback_data=f"{ADMIN_MERCHANT_DEALS_PAGE_PREFIX}{merchant_id}:{page + 1}",
                )
            )
        if nav_buttons:
            builder.row(*nav_buttons)
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await callback.message.answer("Сделки мерчанта:", reply_markup=builder.as_markup())


def _merchant_button_label(record: MerchantRecord) -> str:
    if record.profile and record.profile.username:
        return f"@{record.profile.username}"
    if record.profile and record.profile.full_name:
        return record.profile.full_name
    return str(record.user_id)


def _profile_username_label(profile: UserProfile | None) -> str:
    if profile and profile.username:
        return f"@{profile.username}"
    return "—"


def _admin_deal_status_label(deal: Deal) -> str:
    if deal.status == DealStatus.OPEN:
        return "Ожидаем Мерчанта"
    if deal.status == DealStatus.RESERVED:
        return "Ждем оплату"
    if deal.status == DealStatus.PAID:
        if deal.qr_stage == QrStage.READY and deal.qr_photo_id:
            return "Выдача наличных"
        if deal.qr_stage == QrStage.AWAITING_SELLER_ATTACH:
            return "Подготовка QR"
        if deal.qr_stage == QrStage.AWAITING_BUYER_READY:
            return "Ожидаем готовность"
        if deal.qr_stage == QrStage.AWAITING_SELLER_PHOTO:
            return "Прикрепление QR"
        return "Отправка QR"
    if deal.status == DealStatus.DISPUTE:
        return "Открыт спор"
    if deal.status == DealStatus.COMPLETED:
        return "Завершена"
    if deal.status == DealStatus.CANCELED:
        return "Отменена"
    if deal.status == DealStatus.EXPIRED:
        return "Истекла"
    return deal.status.value


def _admin_deal_button_label(deal: Deal) -> str:
    status = _admin_deal_status_label(deal)
    created = deal.created_at.astimezone(timezone.utc).strftime("%d.%m")
    return f"{deal.hashtag} • {created} — {status}"


def _format_merchant_summary(
    user_id: int,
    profile: UserProfile | None,
    merchant_since: datetime | None,
    deals: List[Deal],
) -> str:
    name = escape(profile.full_name) if profile and profile.full_name else "—"
    username = (
        escape(profile.username) if profile and profile.username else "—"
    )
    since_text = (
        merchant_since.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
        if merchant_since
        else "—"
    )
    total = len(deals)
    success = sum(1 for deal in deals if deal.status == DealStatus.COMPLETED)
    failed = sum(
        1 for deal in deals if deal.status in {DealStatus.CANCELED, DealStatus.EXPIRED}
    )
    lines = [
        "<b>👔 Мерчант</b>",
        f"Имя: {name}",
        f"Ник: {username}",
        f"Мерчант с: {since_text}",
        "",
        f"Сделок всего: {total}",
        f"Успешных: {success}",
        f"Отменённых/истёкших: {failed}",
    ]
    return "\n".join(lines)


def _format_merchant_deals_text(user_id: int, deals: List[Deal]) -> str:
    if not deals:
        return f"У пользователя {user_id} пока нет сделок."
    lines = [f"<b>Сделки мерчанта {user_id}</b>"]
    for idx, deal in enumerate(deals, 1):
        status = STATUS_TITLES.get(deal.status, deal.status.value)
        created = deal.created_at.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
        buyer = deal.buyer_id or "—"
        lines.extend(
            [
                f"{idx}. {deal.hashtag} — {status}",
                f"   Наличные: {_format_decimal(deal.usd_amount)} RUB | USDT: {_format_decimal(deal.usdt_amount)}",
                f"   Продавец: {deal.seller_id} | Покупатель: {buyer}",
                f"   Создано: {created}",
            ]
        )
        if deal.invoice_url:
            lines.append(f"   Invoice: {escape(deal.invoice_url)}")
    return "\n".join(lines)


def _admin_panel_back_markup() -> InlineKeyboardMarkup | None:
    return None


def _format_application(application: MerchantApplication) -> str:
    banks = ", ".join(BANK_OPTIONS.get(bank, bank) for bank in application.banks) or "-"
    username = f"@{application.username}" if application.username else "-"
    uses_personal = "Да" if application.uses_personal_bank else "Нет"
    accepts_risk = "Да" if application.accepts_risk else "Нет"
    created = application.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    status_map = {
        ApplicationStatus.PENDING: "Новая",
        ApplicationStatus.ACCEPTED: "Одобрена",
        ApplicationStatus.REJECTED: "Отклонена",
    }
    status = status_map.get(application.status, application.status.value)
    return (
        f"Заявка #{application.id}\n"
        f"Пользователь: {application.user_id} {username}\n"
        f"Банки: {banks}\n"
        f"Личные банки: {uses_personal}\n"
        f"Берёт риск: {accepts_risk}\n"
        f"Статус: {status}\n"
        f"Создано: {created}"
    )
@router.message(AdminRateState.waiting_rate)
async def admin_rate_input(message: Message, state: FSMContext) -> None:
    deps = get_deps()
    user = message.from_user
    if not user or user.id not in deps.config.admin_ids:
        await message.answer("Нет доступа.")
        await state.clear()
        return
    text = (message.text or "").strip()
    if text.lower() == "отмена":
        await state.clear()
        await message.answer("Изменение курса отменено.")
        return
    try:
        value = Decimal(text.replace(",", "."))
    except Exception:
        await message.answer("Не смог распознать число, попробуй снова.")
        return
    if value <= 0:
        await message.answer("Курс должен быть больше 0.")
        return
    snapshot = await deps.rate_provider.set_rate(usd_rate=value, fee_percent=None)
    await state.clear()
    await message.answer(
        f"Курс обновлён: 1 USDT = {_format_decimal(snapshot.usd_rate)} RUB\nКомиссия: {snapshot.fee_percent}%",
    )


@router.message(AdminRateState.waiting_fee)
async def admin_fee_input(message: Message, state: FSMContext) -> None:
    deps = get_deps()
    user = message.from_user
    if not user or user.id not in deps.config.admin_ids:
        await message.answer("Нет доступа.")
        await state.clear()
        return
    text = (message.text or "").strip()
    if text.lower() == "отмена":
        await state.clear()
        await message.answer("Изменение комиссии отменено.")
        return
    try:
        value = Decimal(text.replace(",", "."))
    except Exception:
        await message.answer("Не смог распознать число, попробуй снова.")
        return
    if value < 0:
        await message.answer("Комиссия не может быть отрицательной.")
        return
    data = await state.get_data()
    fee_kind = data.get("fee_kind", "deal")
    snapshot = await deps.rate_provider.snapshot()
    if fee_kind == "withdraw":
        new_value = await deps.rate_provider.set_withdraw_fee_percent(value)
        deps.config.withdraw_fee_percent = new_value
        await state.clear()
        await message.answer(
            "Комиссия на вывод обновлена:\n"
            f"Комиссия на вывод: {new_value}%\n"
            f"Комиссия на пополнение: {snapshot.fee_percent}%\n"
            f"Курс: 1 USDT = {_format_decimal(snapshot.usd_rate)} RUB",
        )
        return
    snapshot = await deps.rate_provider.set_rate(usd_rate=None, fee_percent=value)
    await state.clear()
    await message.answer(
        "Комиссия на пополнение обновлена:\n"
        f"Комиссия на пополнение: {snapshot.fee_percent}%\n"
        f"Комиссия на вывод: {deps.config.withdraw_fee_percent}%\n"
        f"Курс: 1 USDT = {_format_decimal(snapshot.usd_rate)} RUB",
    )
