"""تنظیمات گروه.

تغییر:
- پلیر همیشه از نظر تنظیمات گروه فعال است.
- set_enabled فقط برای سازگاری با فایل‌های قدیمی پروژه نگه داشته شده.
- قفل پلتفرم و حالت پخش همچنان فعال هستند.
"""

from bot import database as db


LOCK_NONE = "none"
LOCK_YOUTUBE = "youtube"
LOCK_SOUNDCLOUD = "soundcloud"


# ---------------------------------------------------------
# روشن/خاموش پلیر
# ---------------------------------------------------------

def is_enabled(chat_id: int) -> bool:
    """
    پلیر همیشه فعال است.

    این تابع عمداً مقدار enabled دیتابیس را بررسی نمی‌کند
    تا تنظیم خاموش بودن قدیمی نتواند پخش را متوقف کند.
    """
    return True


def set_enabled(chat_id: int, on: bool) -> None:
    """
    برای سازگاری با کدهای قدیمی نگه داشته شده.

    مقدار دیتابیس تغییر می‌کند، اما is_enabled همیشه True
    برمی‌گرداند؛ بنابراین خاموش بودن گروه مانع پخش نمی‌شود.
    """
    db.group_set(
        chat_id,
        enabled=1 if on else 0,
    )


# ---------------------------------------------------------
# قفل پلتفرم
# ---------------------------------------------------------

def get_lock(chat_id: int) -> str:
    try:
        value = db.group_get(chat_id)["lock"]
    except Exception:
        return LOCK_NONE

    if value in (
        LOCK_YOUTUBE,
        LOCK_SOUNDCLOUD,
    ):
        return value

    return LOCK_NONE


def set_lock(chat_id: int, lock: str) -> None:
    if lock not in (
        LOCK_NONE,
        LOCK_YOUTUBE,
        LOCK_SOUNDCLOUD,
    ):
        lock = LOCK_NONE

    db.group_set(
        chat_id,
        lock=lock,
    )


def is_locked(chat_id: int) -> bool:
    return get_lock(chat_id) != LOCK_NONE


# ---------------------------------------------------------
# حالت پخش
# ---------------------------------------------------------

MODE_QUEUE = "queue"
MODE_REPEAT = "repeat"
MODE_RANDOM = "random"

_MODES = (
    MODE_QUEUE,
    MODE_REPEAT,
    MODE_RANDOM,
)


def get_mode(chat_id: int) -> str:
    try:
        value = db.group_get(chat_id)["mode"]
    except Exception:
        return MODE_QUEUE

    if value in _MODES:
        return value

    return MODE_QUEUE


def set_mode(chat_id: int, mode: str) -> None:
    if mode in _MODES:
        db.group_set(
            chat_id,
            mode=mode,
        )
