"""دستور /start، پنل راهنما و مدیریت دکمه‌های /start."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)

from bot import auth
from bot import database as db
from bot import ui
from bot.facmd import fa_command

LOGGER = logging.getLogger("musicbot.start")

_bot_username: Optional[str] = None

# ==================================================================
#                         تنظیمات دکمه‌ها
# ==================================================================

BUTTONS_FILE = Path("start_buttons.json")

# وضعیت موقت عملیات مالک
_button_state: dict[int, str] = {}


def load_start_buttons() -> list[dict]:
    """خواندن دکمه‌های ذخیره‌شده."""

    try:
        if not BUTTONS_FILE.exists():
            return []

        data = json.loads(
            BUTTONS_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(data, list):
            return []

        result = []

        for item in data:
            if not isinstance(item, dict):
                continue

            name = str(
                item.get("name", "")
            ).strip()

            url = str(
                item.get("url", "")
            ).strip()

            if not name or not url:
                continue

            if not (
                url.startswith("https://")
                or url.startswith("http://")
                or url.startswith("tg://")
            ):
                continue

            result.append({
                "name": name,
                "url": url,
            })

        return result

    except Exception as e:
        LOGGER.warning(
            "load start buttons: %s",
            e,
        )
        return []


def save_start_buttons(
    buttons: list[dict],
) -> bool:
    """ذخیره دکمه‌ها."""

    try:
        BUTTONS_FILE.write_text(
            json.dumps(
                buttons,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return True

    except Exception as e:
        LOGGER.error(
            "save start buttons: %s",
            e,
        )

        return False


def add_start_button(
    name: str,
    url: str,
) -> bool:

    buttons = load_start_buttons()

    buttons.append({
        "name": name.strip(),
        "url": url.strip(),
    })

    return save_start_buttons(buttons)


def delete_start_button(
    index: int,
) -> bool:

    buttons = load_start_buttons()

    if index < 0 or index >= len(buttons):
        return False

    buttons.pop(index)

    return save_start_buttons(buttons)


def update_start_button(
    index: int,
    name: str,
    url: str,
) -> bool:

    buttons = load_start_buttons()

    if index < 0 or index >= len(buttons):
        return False

    buttons[index] = {
        "name": name.strip(),
        "url": url.strip(),
    }

    return save_start_buttons(buttons)


def valid_button_url(url: str) -> bool:

    url = url.strip()

    return (
        url.startswith("https://")
        or url.startswith("http://")
        or url.startswith("tg://")
    )


# ==================================================================
#                         اطلاعات ربات
# ==================================================================

async def bot_username(
    client: Client,
) -> str:

    global _bot_username

    if _bot_username:
        return _bot_username

    try:
        me = await client.get_me()

        _bot_username = (
            me.username or ""
        )

    except Exception as e:
        LOGGER.debug(
            "get_me: %s",
            e,
        )

        _bot_username = ""

    return _bot_username


async def bot_profile_photo(
    client: Client,
):
    """گرفتن عکس پروفایل خود ربات."""

    try:
        me = await client.get_me()

        async for photo in client.get_chat_photos(
            me.id,
            limit=1,
        ):
            return photo.file_id

    except Exception as e:
        LOGGER.debug(
            "profile photo: %s",
            e,
        )

    return None


async def add_group_url(
    client: Client,
) -> str:

    uname = await bot_username(
        client
    )

    if not uname:
        return ""

    return (
        f"https://t.me/{uname}"
        "?startgroup=true"
    )


async def pv_url(
    client: Client,
    payload: str = "",
) -> str:

    uname = await bot_username(
        client
    )

    if not uname:
        return ""

    return (
        f"https://t.me/{uname}"
        + (
            f"?start={payload}"
            if payload
            else ""
        )
    )


# ==================================================================
#                    ساخت دکمه‌های /start کاربران
# ==================================================================

def user_start_markup(
    buttons: list[dict],
    add_url: str,
    support_url: str,
) -> InlineKeyboardMarkup:

    rows = []

    # --------------------------------------------------------------
    # دکمه‌های اختصاصی ساخته‌شده توسط مالک
    # --------------------------------------------------------------

    for item in buttons:

        rows.append([
            ui.btn(
                item["name"],
                None,
                ui.PLAIN,
                None,
                url=item["url"],
            )
        ])

    # --------------------------------------------------------------
    # افزودن به گروه
    # --------------------------------------------------------------

    if add_url:

        rows.append([
            ui.btn(
                "➕ افزودن به گروه",
                None,
                ui.GREEN,
                None,
                url=add_url,
            )
        ])

    # --------------------------------------------------------------
    # راهنما + پشتیبانی
    # --------------------------------------------------------------

    rows.append([
        ui.btn(
            "🎧 راهنما",
            "h|main",
            ui.PLAIN,
            ui.EMO_LIST,
        ),
        ui.btn(
            "💬 پشتیبانی",
            None,
            ui.PLAIN,
            None,
            url=support_url,
        ),
    ])

    return ui.kb(rows)


# ==================================================================
#                         متن /start کاربر
# ==================================================================

async def _start_user(
    client: Client,
) -> tuple[
    str,
    list,
    InlineKeyboardMarkup,
]:

    t = ui.Text()

    t.title(
        ui.EMO_HEADPHONE,
        ui.BASE_HEADPHONE,
        "𝗦𝗜𝗟𝗘𝗡𝗧 𝗠𝗨𝗦𝗜𝗖 𝗣𝗟𝗔𝗬𝗘𝗥",
    )

    t.add(
        "\n"
        "🎧 ربات حرفه‌ای پخش موزیک و ویدیو "
        "در ویس‌چت\n\n"
    )

    t.line(
        0,
        "۱. ربات را به گروهت اضافه کن",
    )

    t.line(
        1,
        "۲. ربات را ادمین کن",
    )

    t.line(
        2,
        "۳. ویس‌چت گروه را روشن کن",
    )

    t.emoji(
        ui.alt_arrow(3)
    ).add(
        " ۴. برای پخش بنویس "
    )

    t.code(
        "پخش اهنگ <اسم آهنگ>"
    )

    t.add(
        "\n\n"
    )

    t.italic(
        "✨ آماده‌ای؟ ربات را به گروه اضافه کن."
    )

    buttons = load_start_buttons()

    add_url = await add_group_url(
        client
    )

    support_url = (
        await auth.resolve_support_url(
            client
        )
    )

    markup = user_start_markup(
        buttons,
        add_url,
        support_url,
    )

    return (
        t.text,
        t.entities,
        markup,
    )


# ==================================================================
#                           پنل مالک
# ==================================================================

async def _start_owner(
    client: Client,
) -> tuple[
    str,
    list,
    InlineKeyboardMarkup,
]:

    t = ui.Text()

    t.title(
        ui.EMO_GEAR,
        ui.BASE_ARROW,
        "𝗦𝗜𝗟𝗘𝗡𝗧 𝗠𝗨𝗦𝗜𝗖 𝗣𝗟𝗔𝗬𝗘𝗥",
    )

    t.add(
        "\n"
        "👑 پنل اختصاصی مالک ربات\n\n"
    )

    try:
        groups = len(
            db.get_chats()
        )
    except Exception:
        groups = 0

    buttons_count = len(
        load_start_buttons()
    )

    t.field(
        0,
        "گروه‌های ثبت‌شده",
        f"{ui.fa(groups)} گروه",
    )

    t.field(
        1,
        "دکمه‌های /start",
        f"{ui.fa(buttons_count)} دکمه",
    )

    t.add(
        "\n"
    )

    t.italic(
        "✨ مدیریت ربات از همین‌جا انجام می‌شود."
    )

    add_url = await add_group_url(
        client
    )

    rows = [
        [
            ui.btn(
                "🎛 مدیریت دکمه‌ها",
                "sb|manage",
                ui.BLUE,
                ui.EMO_GEAR,
            )
        ]
    ]

    if add_url:

        rows.append([
            ui.btn(
                "➕ افزودن به گروه",
                None,
                ui.GREEN,
                None,
                url=add_url,
            )
        ])

    rows.append([
        ui.btn(
            "🎧 راهنما",
            "h|main",
            ui.PLAIN,
            ui.EMO_LIST,
        ),
        ui.btn(
            "💬 پشتیبانی",
            None,
            ui.PLAIN,
            None,
            url=await auth.resolve_support_url(
                client
            ),
        ),
    ])

    return (
        t.text,
        t.entities,
        ui.kb(rows),
    )


# ==================================================================
#                           /start گروه
# ==================================================================

async def _start_group(
    client: Client,
) -> tuple[
    str,
    list,
    InlineKeyboardMarkup,
]:

    t = ui.Text()

    t.title(
        ui.EMO_HEADPHONE,
        ui.BASE_HEADPHONE,
        "𝗦𝗜𝗟𝗘𝗡𝗧 𝗠𝗨𝗦𝗜𝗖 𝗣𝗟𝗔𝗬𝗘𝗥",
    )

    t.add(
        "\n"
        "🎧 ربات پخش موزیک و ویدیو\n\n"
    )

    t.emoji(
        ui.alt_arrow(0)
    ).add(
        " برای پخش بنویس : "
    )

    t.code(
        "پخش اهنگ <اسم>"
    )

    t.add(
        "\n\n"
    )

    t.italic(
        "🎵 ویس‌چت گروه باید روشن باشد."
    )

    rows = [
        [
            ui.btn(
                "🎧 راهنما",
                "h|main",
                ui.PLAIN,
                ui.EMO_LIST,
            )
        ]
    ]

    return (
        t.text,
        t.entities,
        ui.kb(rows),
    )


# ==================================================================
#                             /start
# ==================================================================

@Client.on_message(
    filters.command("start")
)
async def start_cmd(
    client: Client,
    message: Message,
):

    if message.from_user:

        db.add_user(
            message.from_user.id
        )

    # --------------------------------------------------------------
    # گروه
    # --------------------------------------------------------------

    if message.chat.type.name != "PRIVATE":

        db.add_chat(
            message.chat.id
        )

        text, ents, kb = await _start_group(
            client
        )

        await message.reply_text(
            text,
            entities=ents,
            reply_markup=kb,
        )

        return

    # --------------------------------------------------------------
    # پیوی
    # --------------------------------------------------------------

    uid = (
        message.from_user.id
        if message.from_user
        else 0
    )

    if uid == auth.OWNER_ID:

        text, ents, kb = await _start_owner(
            client
        )

    else:

        text, ents, kb = await _start_user(
            client
        )

    # --------------------------------------------------------------
    # عکس پروفایل ربات
    # --------------------------------------------------------------

    photo_id = await bot_profile_photo(
        client
    )

    if photo_id:

        try:

            await message.reply_photo(
                photo=photo_id,
                caption=text,
                caption_entities=ents,
                reply_markup=kb,
            )

            return

        except Exception as e:

            LOGGER.warning(
                "send profile photo failed: %s",
                e,
            )

    await message.reply_text(
        text,
        entities=ents,
        reply_markup=kb,
    )


# ==================================================================
#                    مدیریت دکمه‌های /start
# ==================================================================

def buttons_manager_markup() -> InlineKeyboardMarkup:

    buttons = load_start_buttons()

    rows = [
        [
            ui.btn(
                "➕ افزودن دکمه",
                "sb|add",
                ui.GREEN,
                None,
            )
        ]
    ]

    if buttons:

        rows.append([
            ui.btn(
                "✏️ ویرایش دکمه",
                "sb|edit",
                ui.BLUE,
                None,
            ),
            ui.btn(
                "🗑 حذف دکمه",
                "sb|delete",
                ui.RED,
                None,
            ),
        ])

    rows.append([
        ui.btn(
            "🔙 بازگشت",
            "sb|back",
            ui.PLAIN,
            ui.EMO_BACK,
        )
    ])

    return ui.kb(rows)


def buttons_manager_text() -> str:

    buttons = load_start_buttons()

    text = (
        "🎛 𝗦𝗧𝗔𝗥𝗧 𝗕𝗨𝗧𝗧𝗢𝗡 𝗠𝗔𝗡𝗔𝗚𝗘𝗥\n\n"
        "از این بخش دکمه‌های /start را مدیریت کن.\n\n"
    )

    if not buttons:

        text += (
            "📭 هنوز هیچ دکمه‌ای اضافه نشده است."
        )

    else:

        text += "📋 دکمه‌های فعلی:\n\n"

        for i, item in enumerate(
            buttons,
            start=1,
        ):

            text += (
                f"{i}. {item['name']}\n"
                f"🔗 {item['url']}\n\n"
            )

    return text


async def show_buttons_manager(
    query: CallbackQuery,
):

    await query.message.edit_text(
        buttons_manager_text(),
        reply_markup=buttons_manager_markup(),
    )


# ==================================================================
#                         افزودن دکمه
# ==================================================================

async def start_add_button(
    query: CallbackQuery,
):

    uid = (
        query.from_user.id
        if query.from_user
        else 0
    )

    if uid != auth.OWNER_ID:

        await query.answer(
            "⛔ فقط مالک ربات دسترسی دارد.",
            show_alert=True,
        )

        return

    _button_state[uid] = "add_name"

    await query.answer()

    await query.message.reply_text(
        "➕ افزودن دکمه\n\n"
        "نام دکمه را بفرست.\n\n"
        "مثال:\n"
        "📢 کانال ما"
    )


# ==================================================================
#                         حذف دکمه
# ==================================================================

async def show_delete_buttons(
    query: CallbackQuery,
):

    uid = (
        query.from_user.id
        if query.from_user
        else 0
    )

    if uid != auth.OWNER_ID:

        await query.answer(
            "⛔ فقط مالک ربات.",
            show_alert=True,
        )

        return

    buttons = load_start_buttons()

    if not buttons:

        await query.answer(
            "دکمه‌ای برای حذف وجود ندارد.",
            show_alert=True,
        )

        return

    rows = []

    for i, item in enumerate(
        buttons
    ):

        rows.append([
            ui.btn(
                f"🗑 {i + 1}. {item['name']}",
                f"sb|del|{i}",
                ui.RED,
                None,
            )
        ])

    rows.append([
        ui.btn(
            "🔙 بازگشت",
            "sb|manage",
            ui.PLAIN,
            ui.EMO_BACK,
        )
    ])

    await query.answer()

    await query.message.edit_text(
        "🗑 حذف دکمه\n\n"
        "روی دکمه‌ای که می‌خواهی حذف شود بزن:",
        reply_markup=ui.kb(rows),
    )


async def delete_button_confirm(
    query: CallbackQuery,
    index: int,
):

    uid = (
        query.from_user.id
        if query.from_user
        else 0
    )

    if uid != auth.OWNER_ID:

        await query.answer(
            "⛔ دسترسی ندارید.",
            show_alert=True,
        )

        return

    buttons = load_start_buttons()

    if index < 0 or index >= len(buttons):

        await query.answer(
            "دکمه پیدا نشد.",
            show_alert=True,
        )

        return

    name = buttons[index]["name"]

    if delete_start_button(index):

        await query.answer(
            "✅ دکمه حذف شد.",
            show_alert=True,
        )

        await show_buttons_manager(
            query
        )

    else:

        await query.answer(
            "❌ حذف انجام نشد.",
            show_alert=True,
        )


# ==================================================================
#                         ویرایش دکمه
# ==================================================================

async def show_edit_buttons(
    query: CallbackQuery,
):

    uid = (
        query.from_user.id
        if query.from_user
        else 0
    )

    if uid != auth.OWNER_ID:

        await query.answer(
            "⛔ فقط مالک ربات.",
            show_alert=True,
        )

        return

    buttons = load_start_buttons()

    if not buttons:

        await query.answer(
            "دکمه‌ای برای ویرایش وجود ندارد.",
            show_alert=True,
        )

        return

    rows = []

    for i, item in enumerate(
        buttons
    ):

        rows.append([
            ui.btn(
                f"✏️ {i + 1}. {item['name']}",
                f"sb|edit|{i}",
                ui.BLUE,
                None,
            )
        ])

    rows.append([
        ui.btn(
            "🔙 بازگشت",
            "sb|manage",
            ui.PLAIN,
            ui.EMO_BACK,
        )
    ])

    await query.answer()

    await query.message.edit_text(
        "✏️ ویرایش دکمه\n\n"
        "دکمه موردنظر را انتخاب کن:",
        reply_markup=ui.kb(rows),
    )


async def start_edit_button(
    query: CallbackQuery,
    index: int,
):

    uid = (
        query.from_user.id
        if query.from_user
        else 0
    )

    if uid != auth.OWNER_ID:

        await query.answer(
            "⛔ دسترسی ندارید.",
            show_alert=True,
        )

        return

    buttons = load_start_buttons()

    if index < 0 or index >= len(buttons):

        await query.answer(
            "دکمه پیدا نشد.",
            show_alert=True,
        )

        return

    _button_state[uid] = (
        f"edit_name:{index}"
    )

    await query.answer()

    await query.message.reply_text(
        "✏️ ویرایش دکمه\n\n"
        f"نام فعلی:\n"
        f"{buttons[index]['name']}\n\n"
        "نام جدید را بفرست."
    )


# ==================================================================
#                 دریافت پیام‌های مدیریت دکمه
# ==================================================================

@Client.on_message(
    filters.private
    & filters.text
)
async def start_button_messages(
    client: Client,
    message: Message,
):

    if not message.from_user:
        return

    uid = message.from_user.id

    if uid != auth.OWNER_ID:
        return

    state = _button_state.get(uid)

    if not state:
        return

    value = (
        message.text or ""
    ).strip()

    if not value:
        return

    # --------------------------------------------------------------
    # افزودن - نام
    # --------------------------------------------------------------

    if state == "add_name":

        _button_state[uid] = (
            f"add_url:{value}"
        )

        await message.reply_text(
            "🔗 حالا لینک دکمه را بفرست.\n\n"
            "مثال:\n"
            "https://t.me/YourChannel"
        )

        return

    # --------------------------------------------------------------
    # افزودن - لینک
    # --------------------------------------------------------------

    if state.startswith(
        "add_url:"
    ):

        name = state[
            len("add_url:"):
        ]

        url = value

        if not valid_button_url(url):

            await message.reply_text(
                "❌ لینک معتبر نیست.\n\n"
                "لینک باید با یکی از این‌ها شروع شود:\n"
                "https://\n"
                "http://\n"
                "tg://"
            )

            return

        if add_start_button(
            name,
            url,
        ):

            _button_state.pop(
                uid,
                None,
            )

            await message.reply_text(
                "✅ دکمه با موفقیت اضافه شد.\n\n"
                f"نام: {name}\n"
                f"لینک: {url}"
            )

        else:

            await message.reply_text(
                "❌ ذخیره دکمه انجام نشد."
            )

        return

    # --------------------------------------------------------------
    # ویرایش - نام
    # --------------------------------------------------------------

    if state.startswith(
        "edit_name:"
    ):

        try:
            index = int(
                state.split(
                    ":",
                    1,
                )[1]
            )
        except Exception:
            _button_state.pop(
                uid,
                None,
            )
            return

        buttons = load_start_buttons()

        if index < 0 or index >= len(buttons):

            _button_state.pop(
                uid,
                None,
            )

            await message.reply_text(
                "❌ دکمه پیدا نشد."
            )

            return

        _button_state[uid] = (
            f"edit_url:{index}:{value}"
        )

        await message.reply_text(
            "🔗 لینک جدید این دکمه را بفرست."
        )

        return

    # --------------------------------------------------------------
    # ویرایش - لینک
    # --------------------------------------------------------------

    if state.startswith(
        "edit_url:"
    ):

        parts = state.split(
            ":",
            2,
        )

        if len(parts) != 3:

            _button_state.pop(
                uid,
                None,
            )

            return

        try:
            index = int(
                parts[1]
            )
        except Exception:

            _button_state.pop(
                uid,
                None,
            )

            return

        name = parts[2]
        url = value

        if not valid_button_url(url):

            await message.reply_text(
                "❌ لینک معتبر نیست.\n\n"
                "لینک را با https:// یا http:// "
                "یا tg:// بفرست."
            )

            return

        if update_start_button(
            index,
            name,
            url,
        ):

            _button_state.pop(
                uid,
                None,
            )

            await message.reply_text(
                "✅ دکمه با موفقیت ویرایش شد.\n\n"
                f"نام: {name}\n"
                f"لینک: {url}"
            )

        else:

            await message.reply_text(
                "❌ ویرایش انجام نشد."
            )

        return


# ==================================================================
#                       Callback دکمه‌ها
# ==================================================================

@Client.on_callback_query(
    filters.regex(r"^sb\|")
)
async def start_buttons_callback(
    client: Client,
    query: CallbackQuery,
):

    uid = (
        query.from_user.id
        if query.from_user
        else 0
    )

    if uid != auth.OWNER_ID:

        await query.answer(
            "⛔ فقط مالک ربات می‌تواند این بخش را مدیریت کند.",
            show_alert=True,
        )

        return

    data = (
        query.data or ""
    )

    parts = data.split("|")

    if len(parts) < 2:
        return

    action = parts[1]

    # --------------------------------------------------------------
    # مدیریت
    # --------------------------------------------------------------

    if action == "manage":

        await query.answer()

        await show_buttons_manager(
            query
        )

        return

    # --------------------------------------------------------------
    # بازگشت
    # --------------------------------------------------------------

    if action == "back":

        await query.answer()

        text, ents, kb = await _start_owner(
            client
        )

        try:

            await query.message.edit_text(
                text,
                entities=ents,
                reply_markup=kb,
            )

        except Exception:
            pass

        return

    # --------------------------------------------------------------
    # افزودن
    # --------------------------------------------------------------

    if action == "add":

        await start_add_button(
            query
        )

        return

    # --------------------------------------------------------------
    # حذف لیست
    # --------------------------------------------------------------

    if action == "delete":

        await show_delete_buttons(
            query
        )

        return

    # --------------------------------------------------------------
    # حذف نهایی
    # --------------------------------------------------------------

    if action == "del":

        if len(parts) != 3:
            return

        try:
            index = int(
                parts[2]
            )
        except Exception:
            return

        await delete_button_confirm(
            query,
            index,
        )

        return

    # --------------------------------------------------------------
    # ویرایش لیست
    # --------------------------------------------------------------

    if action == "edit":

        if len(parts) == 2:

            await show_edit_buttons(
                query
            )

            return

        try:

            index = int(
                parts[2]
            )

        except Exception:

            await query.answer(
                "دکمه نامعتبر است.",
                show_alert=True,
            )

            return

        await start_edit_button(
            query,
            index,
        )

        return


# ==================================================================
#                          پنل راهنما
# ==================================================================

HELP_MAIN = "main"
HELP_SONG = "song"
HELP_MOVIE = "movie"
HELP_CONTROL = "control"
HELP_PANEL = "panel"

HELP_NODES = (
    HELP_MAIN,
    HELP_SONG,
    HELP_MOVIE,
    HELP_CONTROL,
    HELP_PANEL,
)


LEGACY_NODES = {
    "play_song": HELP_SONG,
    "play_video": HELP_MOVIE,
    "c_pause": HELP_CONTROL,
    "c_resume": HELP_CONTROL,
    "c_skip": HELP_CONTROL,
    "c_stop": HELP_CONTROL,
    "c_queue": HELP_CONTROL,
}


def resolve_node(
    node: str,
) -> str:

    if node in HELP_NODES:
        return node

    return LEGACY_NODES.get(
        node,
        HELP_MAIN,
    )


def _cmd(
    t: ui.Text,
    i: int,
    label: str,
    *commands: str,
) -> ui.Text:

    t.emoji(
        ui.alt_arrow(i)
    ).add(
        f" {label} : "
    )

    for j, c in enumerate(
        commands
    ):

        if j:
            t.add(
                "  ·  "
            )

        t.code(c)

    return t.add(
        "\n"
    )


def _help_main() -> ui.Text:

    t = ui.Text().title(
        ui.EMO_LIST,
        ui.BASE_ARROW,
        "راهنما",
    )

    t.line(
        0,
        "پخش آهنگ و فیلم داخل ویس‌چت گروه",
    )

    t.line(
        1,
        "کنترل کامل با دکمه‌های پنل",
    )

    t.add(
        "\n"
    )

    t.italic(
        "یکی از بخش‌ها را انتخاب کن:"
    )

    return t


def _help_song() -> ui.Text:

    t = ui.Text().title(
        ui.EMO_HEADPHONE,
        ui.BASE_HEADPHONE,
        "پخش آهنگ",
    )

    _cmd(
        t,
        0,
        "با اسم",
        "پخش اهنگ شادمهر دیوانه",
    )

    _cmd(
        t,
        1,
        "با لینک",
        "پخش اهنگ <لینک یوتیوب>",
    )

    _cmd(
        t,
        2,
        "از ساوندکلاد",
        "پخش ساوند کلاد <اسم>",
    )

    _cmd(
        t,
        3,
        "تصادفی از آرشیو",
        "پخش رندوم",
    )

    _cmd(
        t,
        4,
        "فایل تلگرام",
        "روی فایل صوتی ریپلای کن و بنویس «پخش»",
    )

    t.add(
        "\n"
    )

    t.italic(
        "چند آهنگ پشت‌سرهم بفرست تا صف بسازی."
    )

    return t


def _help_movie() -> ui.Text:

    t = ui.Text().title(
        ui.EMO_MOVIE,
        ui.BASE_MOVIE,
        "پخش فیلم",
    )

    _cmd(
        t,
        0,
        "با اسم",
        "پخش فیلم هزارپا",
    )

    _cmd(
        t,
        1,
        "با لینک",
        "پخش فیلم <لینک یوتیوب>",
    )

    _cmd(
        t,
        2,
        "فایل تلگرام",
        "روی ویدیو ریپلای کن و بنویس «پخش فیلم»",
    )

    t.add(
        "\n"
    )

    t.italic(
        "فیلم صف ندارد؛ هر بار یک فیلم پخش می‌شود."
    )

    return t


def _help_control() -> ui.Text:

    t = ui.Text().title(
        ui.EMO_GEAR,
        ui.BASE_ARROW,
        "کنترل پخش",
    )

    _cmd(
        t,
        0,
        "توقف موقت",
        "مکث",
        "توقف",
    )

    _cmd(
        t,
        1,
        "ادامه",
        "ادامه",
        "شروع",
    )

    _cmd(
        t,
        2,
        "بعدی",
        "بعدی",
        "اهنگ بعدی",
        "رد",
    )

    _cmd(
        t,
        3,
        "پایان پخش",
        "خروج",
        "اتمام",
    )

    _cmd(
        t,
        4,
        "لیست پخش",
        "لیست",
        "صف",
    )

    _cmd(
        t,
        5,
        "حالت پخش",
        "حالت پخش",
    )

    _cmd(
        t,
        6,
        "پلتفرم",
        "پلتفرم",
    )

    t.add(
        "\n"
    )

    t.italic(
        "همه‌ی این‌ها با دکمه‌های پنل هم انجام می‌شوند."
    )

    return t


def _help_panel() -> ui.Text:

    t = ui.Text().title(
        ui.EMO_HEADPHONE,
        ui.BASE_HEADPHONE,
        "پنل و دکمه‌ها",
    )

    t.line(
        0,
        "نوار زمان : زمان گذشته، پیشرفت، مدت کل.",
    )

    t.line(
        1,
        "قبلی و بعدی : جابه‌جایی در صف",
    )

    t.line(
        2,
        "مکث و توقف : توقف موقت یا پایان پخش",
    )

    t.line(
        3,
        "صدا : کم و زیاد کردن، دکمه‌ی وسط بیصدا می‌کند",
    )

    t.line(
        4,
        "لیست پخش : صف را می‌بینی",
    )

    t.line(
        5,
        "حالت پخش : صف، تکرار، یا رندوم",
    )

    t.line(
        6,
        "تایمر خواب : پس از مدت انتخابی پخش قطع می‌شود",
    )

    t.line(
        7,
        "پلتفرم : یوتیوب، ساوندکلاد، یا هر دو",
    )

    t.line(
        8,
        "دریافت رسانه : فایل آهنگ در حال پخش را می‌فرستد",
    )

    return t


_BUILDERS = {
    HELP_MAIN: _help_main,
    HELP_SONG: _help_song,
    HELP_MOVIE: _help_movie,
    HELP_CONTROL: _help_control,
    HELP_PANEL: _help_panel,
}


def help_content(
    node: str,
):

    t = _BUILDERS[
        resolve_node(node)
    ]()

    return (
        t.text,
        t.entities,
    )


def help_text(
    node: str,
) -> str:

    return help_content(
        node
    )[0]


def help_entities(
    node: str,
):

    return help_content(
        node
    )[1]


def help_markup(
    node: str,
    support_url: Optional[str] = None,
) -> InlineKeyboardMarkup:

    node = resolve_node(
        node
    )

    link = (
        support_url
        or auth._support_cache["url"]
    )

    if node == HELP_MAIN:

        rows = [
            [
                ui.btn(
                    "🎵 پخش آهنگ",
                    f"h|{HELP_SONG}",
                    ui.PLAIN,
                    ui.EMO_HEADPHONE,
                ),
                ui.btn(
                    "🎬 پخش فیلم",
                    f"h|{HELP_MOVIE}",
                    ui.PLAIN,
                    ui.EMO_MOVIE,
                ),
            ],

            [
                ui.btn(
                    "⚙️ کنترل پخش",
                    f"h|{HELP_CONTROL}",
                    ui.PLAIN,
                    ui.EMO_GEAR,
                ),
                ui.btn(
                    "🎧 پنل و دکمه‌ها",
                    f"h|{HELP_PANEL}",
                    ui.PLAIN,
                    ui.EMO_LIST,
                ),
            ],

            [
                ui.btn(
                    "💬 پشتیبانی",
                    None,
                    ui.BLUE,
                    None,
                    url=link,
                )
            ],

            [
                ui.btn(
                    "❌ بستن راهنما",
                    "h|close",
                    ui.RED,
                    ui.EMO_CLOSE,
                )
            ],
        ]

    else:

        rows = [
            [
                ui.btn(
                    "🔙 بازگشت",
                    f"h|{HELP_MAIN}",
                    ui.PLAIN,
                    ui.EMO_BACK,
                ),

                ui.btn(
                    "❌ بستن راهنما",
                    "h|close",
                    ui.RED,
                    ui.EMO_CLOSE,
                ),
            ]
        ]

    return ui.kb(
        rows
    )


@Client.on_message(
    fa_command([
        "راهنما پلیر",
        "راهنما اهنگ",
        "راهنما آهنگ",
        "راهنما",
    ])
)
async def help_cmd(
    client: Client,
    message: Message,
):

    url = await auth.resolve_support_url(
        client
    )

    text, ents = help_content(
        HELP_MAIN
    )

    await message.reply_text(
        text,
        entities=ents,
        reply_markup=help_markup(
            HELP_MAIN,
            url,
        ),
    )
