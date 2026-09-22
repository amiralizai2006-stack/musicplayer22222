"""
کنترل دسترسی ربات.

تغییر این نسخه:
- در گروه، پیام‌های عادی ربات برای همه اعضا مجاز است.
- دیگر شرط «فقط ادمین گروه» برای استفاده از هندلرهای پیام اعمال نمی‌شود.
- در PV فقط OWNER_ID و کاربران ویژه مجازند.
- guard_callback همچنان فقط OWNER_ID، کاربران ویژه و ادمین‌های گروه را مجاز می‌کند
  تا کنترل‌های مدیریتی دکمه‌ها بدون محدودیت باز نشوند.
"""

import logging
import time

from pyrogram import Client, enums
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot import database as db
import config

LOGGER = logging.getLogger("musicbot.auth")

OWNER_ID = config.OWNER_ID

# ---------------------------------------------------------
# Support URL
# ---------------------------------------------------------

_support_cache = {
    "url": f"tg://user?id={OWNER_ID}",
    "ts": 0.0,
}

_SUPPORT_TTL = 600


async def resolve_support_url(client: Client) -> str:
    """گرفتن یوزرنیم فعلی مالک و ساخت لینک پشتیبانی."""

    now = time.time()

    if now - _support_cache["ts"] < _SUPPORT_TTL:
        return _support_cache["url"]

    url = f"tg://user?id={OWNER_ID}"

    try:
        chat = await client.get_chat(OWNER_ID)

        if getattr(chat, "username", None):
            url = f"https://t.me/{chat.username}"

    except Exception as e:
        LOGGER.debug(
            "resolve support url: %s",
            e,
        )

    _support_cache["url"] = url
    _support_cache["ts"] = now

    return url


def support_kb(
    url: str | None = None,
) -> InlineKeyboardMarkup:
    """دکمه ارتباط با پشتیبانی."""

    link = url or _support_cache["url"]

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💬 ارتباط با پشتیبانی",
                    url=link,
                    style=enums.ButtonStyle.PRIMARY,
                )
            ]
        ]
    )


# ---------------------------------------------------------
# Messages
# ---------------------------------------------------------

DENY_GROUP = (
    "⛔️ **گروه دسترسی ندارد**\n\n"
    "برای مجاز کردن دسترسی با پشتیبانی تماس بگیرید."
)

DENY_USER = (
    "⛔️ **شما دسترسی ندارید**"
)

DENY_CALLBACK = (
    "⛔️ شما دسترسی ندارید\n"
    "با پشتیبانی تماس بگیرید."
)

_DENY_MSG = (
    "⛔️ فقط ادمین‌های گروه می‌توانند از ربات استفاده کنند."
)

_DENY_PV = (
    "⛔️ این ربات فقط برای مالک و ادمین‌های گروه‌هاست."
)


# ---------------------------------------------------------
# Admin cache
# ---------------------------------------------------------

_admin_cache: dict = {}

_CACHE_TTL = 30


async def _admin_ids(
    client: Client,
    chat_id: int,
) -> set:
    """دریافت آیدی ادمین‌های گروه با کش کوتاه."""

    now = time.time()

    hit = _admin_cache.get(chat_id)

    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    ids = set()

    try:
        async for member in client.get_chat_members(
            chat_id,
            filter=enums.ChatMembersFilter.ADMINISTRATORS,
        ):
            if member.user:
                ids.add(member.user.id)

    except Exception as e:
        LOGGER.debug(
            "get admins failed for %s: %s",
            chat_id,
            e,
        )

    _admin_cache[chat_id] = (
        now,
        ids,
    )

    return ids


# ---------------------------------------------------------
# Permission check
# ---------------------------------------------------------

async def is_allowed(
    client: Client,
    chat_id: int,
    user_id: int,
    is_private: bool,
) -> bool:
    """
    بررسی دسترسی مدیریتی.

    این تابع برای بخش‌های مدیریتی همچنان محدودیت دارد:
    - مالک همیشه مجاز است.
    - کاربر ویژه همیشه مجاز است.
    - در PV فقط مالک/کاربر ویژه مجاز است.
    - در گروه فقط ادمین‌ها مجاز هستند.

    توجه:
    guard_message برای پیام‌های گروه عمداً این محدودیت
    را برای استفاده عمومی از ربات اعمال نمی‌کند.
    """

    if user_id == OWNER_ID:
        return True

    if db.is_special(user_id):
        return True

    if is_private:
        return False

    admins = await _admin_ids(
        client,
        chat_id,
    )

    return user_id in admins


# ---------------------------------------------------------
# Message guard
# ---------------------------------------------------------

async def guard_message(
    client: Client,
    message: Message,
) -> bool:
    """
    گارد پیام.

    مهم:
    در گروه همه اعضا اجازه استفاده از دستورات عمومی ربات
    را دارند؛ بنابراین پخش موسیقی دیگر به ادمین بودن وابسته نیست.

    در PV:
    فقط OWNER_ID و کاربران ویژه اجازه دارند.
    """

    user = message.from_user

    if not user:
        # پیام کانال/ناشناس
        return False

    is_private = (
        message.chat.type.name == "PRIVATE"
    )

    # -----------------------------------------------------
    # Private chat
    # -----------------------------------------------------

    if is_private:
        if await is_allowed(
            client,
            message.chat.id,
            user.id,
            True,
        ):
            return True

        try:
            from bot import messages as msg

            url = await resolve_support_url(
                client
            )

            payload = msg.pv_denied(url)

            text, ents, kb = payload

            await message.reply_text(
                text,
                entities=ents,
                reply_markup=(
                    kb
                    if kb and kb.inline_keyboard
                    else None
                ),
            )

        except Exception as e:
            LOGGER.debug(
                "PV deny message failed: %s",
                e,
            )

        return False

    # -----------------------------------------------------
    # Group
    # -----------------------------------------------------
    #
    # مهم‌ترین تغییر:
    # دیگر is_allowed() در گروه بررسی نمی‌شود.
    #
    # بنابراین:
    # پخش
    # صف
    # مکث
    # ادامه
    # بعدی
    # توقف
    # و دستورات عمومی
    #
    # برای همه اعضای گروه قابل استفاده هستند.
    # -----------------------------------------------------

    return True


# ---------------------------------------------------------
# Callback guard
# ---------------------------------------------------------

async def guard_callback(
    client: Client,
    cq: CallbackQuery,
) -> bool:
    """
    گارد دکمه‌ها.

    برای اینکه دکمه‌های مدیریتی توسط هر عضو قابل استفاده نباشند،
    این قسمت همچنان محدودیت مالک/ادمین/کاربر ویژه دارد.
    """

    user = cq.from_user

    if not user:
        return False

    is_private = (
        not cq.message
        or cq.message.chat.type.name == "PRIVATE"
    )

    chat_id = (
        cq.message.chat.id
        if cq.message
        else 0
    )

    if await is_allowed(
        client,
        chat_id,
        user.id,
        is_private,
    ):
        return True

    try:
        await cq.answer(
            DENY_CALLBACK,
            show_alert=True,
        )

    except Exception as e:
        LOGGER.debug(
            "callback deny failed: %s",
            e,
        )

    return False
