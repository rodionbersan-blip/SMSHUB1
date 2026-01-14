from __future__ import annotations

from enum import Enum

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from cachebot.models.user import UserRole


class MenuButtons(str, Enum):
    SHOW_MENU = "📋 Меню"
    BACK = "⬅️ Назад"
    ADMIN_PANEL = "🛠 Админ панель"
    DISPUTES = "⚖️ Спорные ситуации"


class MenuAction(str, Enum):
    SELL = "menu:sell"
    P2P = "menu:p2p"
    OPEN_DEALS = "menu:open_deals"
    MY_DEALS = "menu:my_deals"
    PROFILE = "menu:profile"
    SETTINGS = "menu:settings"
    SETTINGS_MERCHANT = "menu:settings:merchant"
    SETTINGS_SELLER = "menu:settings:seller"
    BALANCE = "menu:balance"


def base_keyboard(is_admin: bool, is_moderator: bool = False) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=MenuButtons.BACK.value), KeyboardButton(text=MenuButtons.SHOW_MENU.value)]]
    rows.append(
        [
            KeyboardButton(
                text="🟦 Открыть мини‑апп",
                web_app=WebAppInfo(url="https://cashnowshop.ru/app"),
            )
        ]
    )
    if is_admin:
        rows.append(
            [
                KeyboardButton(text=MenuButtons.ADMIN_PANEL.value),
            ]
        )
    if is_admin or is_moderator:
        rows.append([KeyboardButton(text=MenuButtons.DISPUTES.value)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Нажми Меню",
    )


def inline_menu(role: UserRole) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if role == UserRole.SELLER:
        builder.button(text="⚡️ Продать", callback_data=MenuAction.SELL.value)
        builder.button(text="💠 P2P", callback_data=MenuAction.P2P.value)
        builder.button(text="📂 Мои сделки", callback_data=MenuAction.MY_DEALS.value)
        builder.button(text="👤 Мой профиль", callback_data=MenuAction.PROFILE.value)
        builder.button(text="⚙️ Настройки", callback_data=MenuAction.SETTINGS.value)
        builder.button(text="💰 Баланс", callback_data=MenuAction.BALANCE.value)
        builder.adjust(2, 2, 2)
    else:
        builder.button(text="📋 Купить", callback_data=MenuAction.OPEN_DEALS.value)
        builder.button(text="💠 P2P", callback_data=MenuAction.P2P.value)
        builder.button(text="📂 Мои сделки", callback_data=MenuAction.MY_DEALS.value)
        builder.button(text="👤 Мой профиль", callback_data=MenuAction.PROFILE.value)
        builder.button(text="⚙️ Настройки", callback_data=MenuAction.SETTINGS.value)
        builder.button(text="💰 Баланс", callback_data=MenuAction.BALANCE.value)
        builder.adjust(2, 2, 2)
    return builder.as_markup()
