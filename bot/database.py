"""دیتابیس محلی SQLite — فقط برای داده‌های ماندگار (لیست گروه‌های فعال و تنظیمات)."""
import os
import sqlite3
import threading
from typing import List, Optional

import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        # اطمینان از وجود پوشه‌ی مقصد فایل دیتابیس
        db_dir = os.path.dirname(config.DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        _conn = sqlite3.connect(
            config.DB_PATH,
            check_same_thread=False,
        )
        _conn.row_factory = sqlite3.Row
        _init_schema(_conn)

    return _conn


def close() -> None:
    """اتصال دیتابیس را می‌بندد."""
    global _conn

    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:  # noqa: BLE001
                pass

            _conn = None


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- کش فایل‌های دانلودشده
        CREATE TABLE IF NOT EXISTS media_cache (
            video_id   TEXT PRIMARY KEY,
            path       TEXT NOT NULL,
            title      TEXT,
            duration   INTEGER,
            is_video   INTEGER DEFAULT 0,
            last_used  REAL DEFAULT 0
        );

        -- صف پخش پایدار
        CREATE TABLE IF NOT EXISTS play_queue (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   INTEGER NOT NULL,
            pos       INTEGER NOT NULL,
            data      TEXT NOT NULL
        );

        -- کاربران ویژه
        CREATE TABLE IF NOT EXISTS special_users (
            user_id  INTEGER PRIMARY KEY,
            name     TEXT DEFAULT '',
            added_at REAL DEFAULT 0
        );

        -- تنظیمات هر گروه
        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id   INTEGER PRIMARY KEY,
            enabled   INTEGER DEFAULT 0,
            lock      TEXT DEFAULT 'none',
            platform  TEXT DEFAULT 'both',
            mode      TEXT DEFAULT 'queue'
        );

        -- آرشیو آهنگ در کانال
        CREATE TABLE IF NOT EXISTS channel_songs (
            key         TEXT PRIMARY KEY,
            file_id     TEXT NOT NULL,
            message_id  INTEGER,
            title       TEXT,
            duration    INTEGER DEFAULT 0,
            is_video    INTEGER DEFAULT 0,
            added_at    REAL DEFAULT 0,
            performer   TEXT DEFAULT '',
            file_size   INTEGER DEFAULT 0,
            source      TEXT DEFAULT '',
            added_by    INTEGER DEFAULT 0,
            url         TEXT DEFAULT ''
        );

        -- اشتراک هر گروه
        CREATE TABLE IF NOT EXISTS subscriptions (
            chat_id       INTEGER PRIMARY KEY,
            tier          TEXT DEFAULT 'basic',
            expires_at    REAL DEFAULT 0,
            buyer_id      INTEGER DEFAULT 0,
            started_at    REAL DEFAULT 0,
            last_notified REAL DEFAULT 0
        );

        -- سفارش‌های پرداخت
        CREATE TABLE IF NOT EXISTS orders (
            id         TEXT PRIMARY KEY,
            buyer_id   INTEGER,
            chat_id    INTEGER,
            tier       TEXT,
            months     INTEGER,
            amount     INTEGER,
            method     TEXT,
            status     TEXT DEFAULT 'pending',
            ref        TEXT DEFAULT '',
            created_at REAL,
            paid_at    REAL DEFAULT 0
        );

        -- تنظیمات پرداخت
        CREATE TABLE IF NOT EXISTS pay_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        -- شماره کارت‌های پرداخت
        CREATE TABLE IF NOT EXISTS pay_cards (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            number   TEXT NOT NULL,
            holder   TEXT DEFAULT '',
            added_at REAL DEFAULT 0
        );

        -- کدهای هدیه
        CREATE TABLE IF NOT EXISTS gift_codes (
            code       TEXT PRIMARY KEY,
            tier       TEXT DEFAULT 'basic',
            months     INTEGER DEFAULT 1,
            max_uses   INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            created_at REAL DEFAULT 0
        );

        -- ==========================================================
        -- دکمه‌های قابل مدیریت /start
        -- ==========================================================
        CREATE TABLE IF NOT EXISTS start_buttons (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT NOT NULL,
            url        TEXT NOT NULL,
            position   INTEGER DEFAULT 0,
            enabled    INTEGER DEFAULT 1
        );
        """
    )

    conn.commit()

    _add_columns(conn)
    _migrate_from_settings(conn)


# ستون‌هایی که ممکن است در دیتابیس‌های قدیمی نباشند
_EXTRA_COLUMNS = [
    (
        "group_settings",
        "mode",
        "TEXT DEFAULT 'queue'",
    ),

    (
        "group_settings",
        "free_until",
        "REAL DEFAULT 0",
    ),

    (
        "subscriptions",
        "paused_at",
        "REAL DEFAULT 0",
    ),

    (
        "channel_songs",
        "performer",
        "TEXT DEFAULT ''",
    ),

    (
        "channel_songs",
        "file_size",
        "INTEGER DEFAULT 0",
    ),

    (
        "channel_songs",
        "source",
        "TEXT DEFAULT ''",
    ),

    (
        "channel_songs",
        "added_by",
        "INTEGER DEFAULT 0",
    ),

    (
        "channel_songs",
        "url",
        "TEXT DEFAULT ''",
    ),
]


def _add_columns(conn: sqlite3.Connection) -> None:
    """ستون‌های جدید را به دیتابیس‌های قدیمی اضافه می‌کند."""

    for table, column, decl in _EXTRA_COLUMNS:
        try:
            cols = [
                r[1]
                for r in conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            ]

            if column not in cols:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {decl}"
                )
                conn.commit()

        except Exception:  # noqa: BLE001
            pass


def _migrate_from_settings(conn) -> None:
    """مهاجرت داده‌های قدیمی از settings."""

    try:
        rows = conn.execute(
            "SELECT key, value FROM settings"
        ).fetchall()

    except Exception:  # noqa: BLE001
        return

    migrated = 0

    for r in rows:
        key = r["key"]
        val = r["value"]

        try:
            if key.startswith("special_"):
                uid = int(
                    key.split("_", 1)[1]
                )

                conn.execute(
                    "INSERT OR IGNORE INTO special_users"
                    "(user_id, name, added_at) "
                    "VALUES (?,?,0)",
                    (
                        uid,
                        val if val != "1" else "",
                    ),
                )

                conn.execute(
                    "DELETE FROM settings WHERE key=?",
                    (key,),
                )

                migrated += 1

            elif key.startswith("player_on_"):
                cid = int(
                    key.split("player_on_", 1)[1]
                )

                conn.execute(
                    "INSERT INTO group_settings"
                    "(chat_id, enabled) VALUES (?,?) "
                    "ON CONFLICT(chat_id) DO UPDATE SET "
                    "enabled=excluded.enabled",
                    (
                        cid,
                        1 if val == "1" else 0,
                    ),
                )

                conn.execute(
                    "DELETE FROM settings WHERE key=?",
                    (key,),
                )

                migrated += 1

            elif key.startswith("player_lock_"):
                cid = int(
                    key.split("player_lock_", 1)[1]
                )

                conn.execute(
                    "INSERT INTO group_settings"
                    "(chat_id, lock) VALUES (?,?) "
                    "ON CONFLICT(chat_id) DO UPDATE SET "
                    "lock=excluded.lock",
                    (
                        cid,
                        val,
                    ),
                )

                conn.execute(
                    "DELETE FROM settings WHERE key=?",
                    (key,),
                )

                migrated += 1

            elif key.startswith("platform_"):
                cid = int(
                    key.split("platform_", 1)[1]
                )

                conn.execute(
                    "INSERT INTO group_settings"
                    "(chat_id, platform) VALUES (?,?) "
                    "ON CONFLICT(chat_id) DO UPDATE SET "
                    "platform=excluded.platform",
                    (
                        cid,
                        val,
                    ),
                )

                conn.execute(
                    "DELETE FROM settings WHERE key=?",
                    (key,),
                )

                migrated += 1

        except (ValueError, IndexError):
            pass

    if migrated:
        conn.commit()


# ================================================================
# صف پخش پایدار
# ================================================================

def queue_save(
    chat_id: int,
    tracks: list,
) -> None:
    """کل وضعیت صف یک گروه را ذخیره می‌کند."""

    import json

    with _lock:
        conn = _connect()

        conn.execute(
            "DELETE FROM play_queue WHERE chat_id=?",
            (chat_id,),
        )

        for pos, t in enumerate(tracks):
            conn.execute(
                "INSERT INTO play_queue"
                "(chat_id, pos, data) VALUES (?,?,?)",
                (
                    chat_id,
                    pos,
                    json.dumps(
                        t,
                        ensure_ascii=False,
                    ),
                ),
            )

        conn.commit()


def queue_load_all() -> dict:
    """همه صف‌های ذخیره‌شده را برمی‌گرداند."""

    import json

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT chat_id, pos, data "
            "FROM play_queue "
            "ORDER BY chat_id, pos"
        ).fetchall()

    out: dict = {}

    for r in rows:
        try:
            out.setdefault(
                r["chat_id"],
                [],
            ).append(
                json.loads(r["data"])
            )

        except Exception:  # noqa: BLE001
            pass

    return out


def queue_clear(
    chat_id: int,
) -> None:

    with _lock:
        conn = _connect()

        conn.execute(
            "DELETE FROM play_queue WHERE chat_id=?",
            (chat_id,),
        )

        conn.commit()


# ================================================================
# آرشیو آهنگ
# ================================================================

def _col(
    row,
    name,
    default,
):
    try:
        v = row[name]
    except (IndexError, KeyError):
        return default

    return default if v is None else v


def archive_get(
    key: str,
) -> Optional[dict]:

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT key, file_id, message_id, title, duration, "
            "is_video, performer, file_size, source, added_by, "
            "url, added_at "
            "FROM channel_songs WHERE key=?",
            (key,),
        ).fetchone()

        if not row:
            return None

        return {
            "key": row["key"],
            "file_id": row["file_id"],
            "message_id": row["message_id"],
            "title": row["title"],
            "duration": row["duration"],
            "is_video": bool(row["is_video"]),
            "performer": _col(
                row,
                "performer",
                "",
            ),
            "file_size": _col(
                row,
                "file_size",
                0,
            ),
            "source": _col(
                row,
                "source",
                "",
            ),
            "added_by": _col(
                row,
                "added_by",
                0,
            ),
            "url": _col(
                row,
                "url",
                "",
            ),
            "added_at": _col(
                row,
                "added_at",
                0.0,
            ),
        }


def archive_put(
    key: str,
    file_id: str,
    message_id: int,
    title: str,
    duration: int,
    is_video: bool,
    performer: str = "",
    file_size: int = 0,
    source: str = "",
    added_by: int = 0,
    url: str = "",
) -> None:

    import time

    with _lock:
        conn = _connect()

        conn.execute(
            "INSERT INTO channel_songs"
            "(key, file_id, message_id, title, duration, "
            "is_video, added_at, performer, file_size, source, "
            "added_by, url) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "file_id=excluded.file_id, "
            "message_id=excluded.message_id, "
            "title=excluded.title, "
            "duration=excluded.duration, "
            "is_video=excluded.is_video, "
            "performer=excluded.performer, "
            "file_size=excluded.file_size, "
            "source=excluded.source, "
            "added_by=excluded.added_by, "
            "url=excluded.url",

            (
                key,
                file_id,
                message_id,
                title,
                duration,
                1 if is_video else 0,
                time.time(),
                performer,
                int(file_size or 0),
                source,
                int(added_by or 0),
                url,
            ),
        )

        conn.commit()


def archive_by_message(
    message_id: int,
) -> Optional[dict]:

    if not message_id:
        return None

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT key, file_id, message_id, title, duration, "
            "is_video, performer, file_size, source, added_by, "
            "url, added_at "
            "FROM channel_songs WHERE message_id=?",
            (int(message_id),),
        ).fetchone()

        if not row:
            return None

        return {
            "key": row["key"],
            "file_id": row["file_id"],
            "message_id": row["message_id"],
            "title": row["title"],
            "duration": row["duration"],
            "is_video": bool(row["is_video"]),
            "performer": _col(
                row,
                "performer",
                "",
            ),
            "file_size": _col(
                row,
                "file_size",
                0,
            ),
            "source": _col(
                row,
                "source",
                "",
            ),
            "added_by": _col(
                row,
                "added_by",
                0,
            ),
            "url": _col(
                row,
                "url",
                "",
            ),
            "added_at": _col(
                row,
                "added_at",
                0.0,
            ),
        }


def archive_by_short(
    short: str,
) -> Optional[dict]:

    if not short:
        return None

    if not short.startswith("h:"):
        return archive_get(short)

    import hashlib

    target = short[2:]

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT key FROM channel_songs"
        ).fetchall()

    for r in rows:
        if (
            hashlib.sha1(
                r["key"].encode()
            ).hexdigest()[:16]
            == target
        ):
            return archive_get(r["key"])

    return None


def archive_count() -> int:

    with _lock:
        conn = _connect()

        return conn.execute(
            "SELECT COUNT(*) AS c FROM channel_songs"
        ).fetchone()["c"]


def archive_delete(
    key: str = "",
    message_id: int = 0,
) -> Optional[dict]:

    with _lock:
        conn = _connect()

        if message_id:
            row = conn.execute(
                "SELECT key, title, message_id, performer, "
                "duration, source "
                "FROM channel_songs "
                "WHERE message_id=?",
                (message_id,),
            ).fetchone()

        elif key:
            row = conn.execute(
                "SELECT key, title, message_id, performer, "
                "duration, source "
                "FROM channel_songs "
                "WHERE key=?",
                (key,),
            ).fetchone()

        else:
            return None

        if not row:
            return None

        conn.execute(
            "DELETE FROM channel_songs WHERE key=?",
            (row["key"],),
        )

        conn.commit()

        return {
            "key": row["key"],
            "title": row["title"],
            "message_id": row["message_id"],
            "performer": _col(
                row,
                "performer",
                "",
            ),
            "duration": _col(
                row,
                "duration",
                0,
            ),
            "source": _col(
                row,
                "source",
                "",
            ),
        }


def archive_random(
    audio_only: bool = True,
) -> Optional[dict]:

    with _lock:
        conn = _connect()

        sql = (
            "SELECT key, file_id, message_id, title, duration, "
            "is_video, performer, file_size, source, added_by, "
            "url, added_at "
            "FROM channel_songs"
        )

        if audio_only:
            sql += " WHERE is_video=0"

        sql += " ORDER BY RANDOM() LIMIT 1"

        row = conn.execute(sql).fetchone()

        if not row:
            return None

        return {
            "key": row["key"],
            "file_id": row["file_id"],
            "message_id": row["message_id"],
            "title": row["title"],
            "duration": row["duration"],
            "is_video": bool(row["is_video"]),
            "performer": _col(
                row,
                "performer",
                "",
            ),
            "file_size": _col(
                row,
                "file_size",
                0,
            ),
            "source": _col(
                row,
                "source",
                "",
            ),
            "added_by": _col(
                row,
                "added_by",
                0,
            ),
            "url": _col(
                row,
                "url",
                "",
            ),
            "added_at": _col(
                row,
                "added_at",
                0.0,
            ),
        }


# ================================================================
# کش رسانه
# ================================================================

def cache_get(
    video_id: str,
) -> Optional[dict]:

    import time

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT video_id, path, title, duration, is_video "
            "FROM media_cache WHERE video_id=?",
            (video_id,),
        ).fetchone()

        if not row:
            return None

        conn.execute(
            "UPDATE media_cache SET last_used=? "
            "WHERE video_id=?",
            (
                time.time(),
                video_id,
            ),
        )

        conn.commit()

        return {
            "video_id": row["video_id"],
            "path": row["path"],
            "title": row["title"],
            "duration": row["duration"],
            "is_video": bool(row["is_video"]),
        }


def cache_put(
    video_id: str,
    path: str,
    title: str,
    duration: int,
    is_video: bool,
) -> None:

    import time

    with _lock:
        conn = _connect()

        conn.execute(
            "INSERT INTO media_cache"
            "(video_id, path, title, duration, is_video, last_used) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(video_id) DO UPDATE SET "
            "path=excluded.path, "
            "title=excluded.title, "
            "duration=excluded.duration, "
            "is_video=excluded.is_video, "
            "last_used=excluded.last_used",

            (
                video_id,
                path,
                title,
                duration,
                1 if is_video else 0,
                time.time(),
            ),
        )

        conn.commit()


def cache_prune(
    keep: int = 10,
) -> List[str]:

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT video_id, path "
            "FROM media_cache "
            "ORDER BY last_used DESC"
        ).fetchall()

        to_delete = rows[keep:]
        paths = []

        for r in to_delete:
            conn.execute(
                "DELETE FROM media_cache "
                "WHERE video_id=?",
                (r["video_id"],),
            )

            paths.append(r["path"])

        conn.commit()

        return paths


def cache_paths() -> List[str]:

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT path FROM media_cache"
        ).fetchall()

        return [
            r["path"]
            for r in rows
        ]


# ================================================================
# گروه‌ها
# ================================================================

def add_chat(
    chat_id: int,
) -> None:

    with _lock:
        conn = _connect()

        conn.execute(
            "INSERT OR IGNORE INTO chats(chat_id) VALUES (?)",
            (chat_id,),
        )

        conn.commit()


def get_chats() -> List[int]:

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT chat_id FROM chats"
        ).fetchall()

        return [
            r["chat_id"]
            for r in rows
        ]


# ================================================================
# کاربران
# ================================================================

def add_user(
    user_id: int,
) -> None:

    with _lock:
        conn = _connect()

        conn.execute(
            "INSERT OR IGNORE INTO users(user_id) VALUES (?)",
            (user_id,),
        )

        conn.commit()


def get_users() -> List[int]:

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT user_id FROM users"
        ).fetchall()

        return [
            r["user_id"]
            for r in rows
        ]


# ================================================================
# کاربران ویژه
# ================================================================

def add_special(
    user_id: int,
    name: str = "",
) -> None:

    import time

    with _lock:
        conn = _connect()

        conn.execute(
            "INSERT INTO special_users"
            "(user_id, name, added_at) "
            "VALUES (?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "name=excluded.name",

            (
                user_id,
                name,
                time.time(),
            ),
        )

        conn.commit()


def remove_special(
    user_id: int,
) -> None:

    with _lock:
        conn = _connect()

        conn.execute(
            "DELETE FROM special_users "
            "WHERE user_id=?",
            (user_id,),
        )

        conn.commit()


def is_special(
    user_id: int,
) -> bool:

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT 1 FROM special_users "
            "WHERE user_id=?",
            (user_id,),
        ).fetchone()

        return row is not None


def special_name(
    user_id: int,
) -> str:

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT name FROM special_users "
            "WHERE user_id=?",
            (user_id,),
        ).fetchone()

        return row["name"] if row else ""


def list_special() -> List[int]:

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT user_id FROM special_users "
            "ORDER BY added_at"
        ).fetchall()

        return [
            r["user_id"]
            for r in rows
        ]


# ================================================================
# تنظیمات گروه
# ================================================================

def group_get(
    chat_id: int,
) -> dict:

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT enabled, lock, platform, mode, free_until "
            "FROM group_settings "
            "WHERE chat_id=?",
            (chat_id,),
        ).fetchone()

        if not row:
            return {
                "enabled": 0,
                "lock": "none",
                "platform": "both",
                "mode": "queue",
                "free_until": 0.0,
            }

        return {
            "enabled": row["enabled"],
            "lock": row["lock"],
            "platform": row["platform"],
            "mode": row["mode"] or "queue",
            "free_until": row["free_until"] or 0.0,
        }


def group_set(
    chat_id: int,
    **fields,
) -> None:

    allowed = {
        "enabled",
        "lock",
        "platform",
        "mode",
        "free_until",
    }

    fields = {
        k: v
        for k, v in fields.items()
        if k in allowed
    }

    if not fields:
        return

    with _lock:
        conn = _connect()

        conn.execute(
            "INSERT INTO group_settings(chat_id) "
            "VALUES (?) "
            "ON CONFLICT(chat_id) DO NOTHING",
            (chat_id,),
        )

        sets = ", ".join(
            f"{k}=?"
            for k in fields
        )

        conn.execute(
            f"UPDATE group_settings "
            f"SET {sets} "
            f"WHERE chat_id=?",
            (
                *fields.values(),
                chat_id,
            ),
        )

        conn.commit()


# ================================================================
# تنظیمات کلید/مقدار
# ================================================================

def set_setting(
    key: str,
    value: str,
) -> None:

    with _lock:
        conn = _connect()

        conn.execute(
            "INSERT INTO settings(key, value) "
            "VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value=excluded.value",
            (
                key,
                value,
            ),
        )

        conn.commit()


def get_setting(
    key: str,
    default: str | None = None,
) -> str | None:

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT value FROM settings "
            "WHERE key=?",
            (key,),
        ).fetchone()

        return row["value"] if row else default


# ================================================================
# اشتراک گروه‌ها
# ================================================================

def sub_get(
    chat_id: int,
) -> Optional[dict]:

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT chat_id, tier, expires_at, buyer_id, "
            "started_at, last_notified, paused_at "
            "FROM subscriptions "
            "WHERE chat_id=?",
            (chat_id,),
        ).fetchone()

        if not row:
            return None

        return dict(row)


def sub_set(
    chat_id: int,
    **fields,
) -> None:

    allowed = {
        "tier",
        "expires_at",
        "buyer_id",
        "started_at",
        "last_notified",
        "paused_at",
    }

    fields = {
        k: v
        for k, v in fields.items()
        if k in allowed
    }

    if not fields:
        return

    with _lock:
        conn = _connect()

        conn.execute(
            "INSERT INTO subscriptions(chat_id) "
            "VALUES (?) "
            "ON CONFLICT(chat_id) DO NOTHING",
            (chat_id,),
        )

        sets = ", ".join(
            f"{k}=?"
            for k in fields
        )

        conn.execute(
            f"UPDATE subscriptions "
            f"SET {sets} "
            f"WHERE chat_id=?",
            (
                *fields.values(),
                chat_id,
            ),
        )

        conn.commit()


def sub_delete(
    chat_id: int,
) -> None:

    with _lock:
        conn = _connect()

        conn.execute(
            "DELETE FROM subscriptions "
            "WHERE chat_id=?",
            (chat_id,),
        )

        conn.commit()


def sub_all() -> list:

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT chat_id, tier, expires_at, buyer_id, "
            "started_at, last_notified "
            "FROM subscriptions "
            "ORDER BY expires_at"
        ).fetchall()

        return [
            dict(r)
            for r in rows
        ]


def sub_expired(
    now_ts: float,
) -> list:

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT chat_id, tier, expires_at, buyer_id, "
            "last_notified "
            "FROM subscriptions "
            "WHERE expires_at>0 "
            "AND expires_at<?",
            (now_ts,),
        ).fetchall()

        return [
            dict(r)
            for r in rows
        ]


# ================================================================
# سفارش‌های پرداخت
# ================================================================

def order_create(
    oid: str,
    buyer_id: int,
    chat_id: int,
    tier: str,
    months: int,
    amount: int,
    method: str,
) -> None:

    import time

    with _lock:
        conn = _connect()

        conn.execute(
            "INSERT INTO orders"
            "(id, buyer_id, chat_id, tier, months, amount, "
            "method, status, created_at) "
            "VALUES (?,?,?,?,?,?,?, 'pending', ?)",

            (
                oid,
                buyer_id,
                chat_id,
                tier,
                months,
                amount,
                method,
                time.time(),
            ),
        )

        conn.commit()


def order_get(
    oid: str,
) -> Optional[dict]:

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT * FROM orders "
            "WHERE id=?",
            (oid,),
        ).fetchone()

        return dict(row) if row else None


def order_set_status(
    oid: str,
    status: str,
    ref: str = "",
) -> None:

    import time

    with _lock:
        conn = _connect()

        paid = (
            time.time()
            if status == "paid"
            else 0
        )

        conn.execute(
            "UPDATE orders "
            "SET status=?, ref=?, paid_at=? "
            "WHERE id=?",
            (
                status,
                ref,
                paid,
                oid,
            ),
        )

        conn.commit()


def orders_pending() -> list:

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT * FROM orders "
            "WHERE status='pending' "
            "ORDER BY created_at DESC "
            "LIMIT 50"
        ).fetchall()

        return [
            dict(r)
            for r in rows
        ]


def orders_all_paid() -> list:

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT id, ref "
            "FROM orders "
            "WHERE status='paid' "
            "AND ref!=''"
        ).fetchall()

        return [
            dict(r)
            for r in rows
        ]


# ================================================================
# تنظیمات پرداخت
# ================================================================

def pay_get(
    key: str,
    default: str = "",
) -> str:

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT value FROM pay_settings "
            "WHERE key=?",
            (key,),
        ).fetchone()

        return row["value"] if row else default


def pay_set(
    key: str,
    value: str,
) -> None:

    with _lock:
        conn = _connect()

        conn.execute(
            "INSERT INTO pay_settings(key, value) "
            "VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value=excluded.value",
            (
                key,
                str(value),
            ),
        )

        conn.commit()


# ================================================================
# کارت‌های پرداخت
# ================================================================

def cards_all() -> List[dict]:

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT id, number, holder "
            "FROM pay_cards "
            "ORDER BY id"
        ).fetchall()

        return [
            dict(r)
            for r in rows
        ]


def card_add(
    number: str,
    holder: str = "",
) -> int:

    import time

    with _lock:
        conn = _connect()

        cur = conn.execute(
            "INSERT INTO pay_cards"
            "(number, holder, added_at) "
            "VALUES (?,?,?)",
            (
                number.strip(),
                holder.strip(),
                time.time(),
            ),
        )

        conn.commit()

        return int(
            cur.lastrowid or 0
        )


def card_delete(
    card_id: int,
) -> bool:

    with _lock:
        conn = _connect()

        cur = conn.execute(
            "DELETE FROM pay_cards "
            "WHERE id=?",
            (card_id,),
        )

        conn.commit()

        return cur.rowcount > 0


# ================================================================
# کدهای هدیه
# ================================================================

def gift_create(
    code: str,
    tier: str,
    months: int,
    max_uses: int = 1,
) -> None:

    import time

    with _lock:
        conn = _connect()

        conn.execute(
            "INSERT INTO gift_codes"
            "(code, tier, months, max_uses, used_count, created_at) "
            "VALUES (?,?,?,?,0,?) "
            "ON CONFLICT(code) DO UPDATE SET "
            "tier=excluded.tier, "
            "months=excluded.months, "
            "max_uses=excluded.max_uses",

            (
                code,
                tier,
                months,
                max_uses,
                time.time(),
            ),
        )

        conn.commit()


def gift_get(
    code: str,
) -> Optional[dict]:

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT * FROM gift_codes "
            "WHERE code=?",
            (code,),
        ).fetchone()

        return dict(row) if row else None


def gift_redeem(
    code: str,
) -> bool:

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT used_count, max_uses "
            "FROM gift_codes "
            "WHERE code=?",
            (code,),
        ).fetchone()

        if (
            not row
            or row["used_count"] >= row["max_uses"]
        ):
            return False

        conn.execute(
            "UPDATE gift_codes "
            "SET used_count=used_count+1 "
            "WHERE code=?",
            (code,),
        )

        conn.commit()

        return True


def gift_all() -> list:

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT * FROM gift_codes "
            "ORDER BY created_at DESC "
            "LIMIT 50"
        ).fetchall()

        return [
            dict(r)
            for r in rows
        ]


# ================================================================
# دکمه‌های /start
# ================================================================

def start_buttons_all() -> List[dict]:
    """فقط دکمه‌های فعال را به ترتیب نمایش برمی‌گرداند."""

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT id, title, url, position, enabled "
            "FROM start_buttons "
            "WHERE enabled=1 "
            "ORDER BY position ASC, id ASC"
        ).fetchall()

        return [
            dict(r)
            for r in rows
        ]


def start_buttons_all_admin() -> List[dict]:
    """همه دکمه‌ها را برای پنل مالک برمی‌گرداند."""

    with _lock:
        conn = _connect()

        rows = conn.execute(
            "SELECT id, title, url, position, enabled "
            "FROM start_buttons "
            "ORDER BY position ASC, id ASC"
        ).fetchall()

        return [
            dict(r)
            for r in rows
        ]


def start_button_get(
    button_id: int,
) -> Optional[dict]:
    """یک دکمه را بر اساس ID پیدا می‌کند."""

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT id, title, url, position, enabled "
            "FROM start_buttons "
            "WHERE id=?",
            (int(button_id),),
        ).fetchone()

        return dict(row) if row else None


def start_button_add(
    title: str,
    url: str,
) -> int:
    """یک دکمه جدید اضافه می‌کند."""

    title = title.strip()
    url = url.strip()

    if not title or not url:
        return 0

    with _lock:
        conn = _connect()

        row = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS pos "
            "FROM start_buttons"
        ).fetchone()

        position = int(
            row["pos"] or 0
        )

        cur = conn.execute(
            "INSERT INTO start_buttons"
            "(title, url, position, enabled) "
            "VALUES (?, ?, ?, 1)",
            (
                title,
                url,
                position,
            ),
        )

        conn.commit()

        return int(
            cur.lastrowid or 0
        )


def start_button_update(
    button_id: int,
    title: str,
    url: str,
) -> bool:
    """نام و لینک یک دکمه را تغییر می‌دهد."""

    title = title.strip()
    url = url.strip()

    if not title or not url:
        return False

    with _lock:
        conn = _connect()

        cur = conn.execute(
            "UPDATE start_buttons "
            "SET title=?, url=? "
            "WHERE id=?",
            (
                title,
                url,
                int(button_id),
            ),
        )

        conn.commit()

        return cur.rowcount > 0


def start_button_delete(
    button_id: int,
) -> bool:
    """یک دکمه را حذف می‌کند."""

    with _lock:
        conn = _connect()

        cur = conn.execute(
            "DELETE FROM start_buttons "
            "WHERE id=?",
            (int(button_id),),
        )

        conn.commit()

        return cur.rowcount > 0


def start_button_set_enabled(
    button_id: int,
    enabled: bool,
) -> bool:
    """دکمه را فعال یا غیرفعال می‌کند."""

    with _lock:
        conn = _connect()

        cur = conn.execute(
            "UPDATE start_buttons "
            "SET enabled=? "
            "WHERE id=?",
            (
                1 if enabled else 0,
                int(button_id),
            ),
        )

        conn.commit()

        return cur.rowcount > 0


def start_buttons_reorder(
    ordered_ids: List[int],
) -> None:
    """ترتیب دکمه‌ها را تنظیم می‌کند."""

    with _lock:
        conn = _connect()

        for position, button_id in enumerate(
            ordered_ids
        ):
            conn.execute(
                "UPDATE start_buttons "
                "SET position=? "
                "WHERE id=?",
                (
                    position,
                    int(button_id),
                ),
            )

        conn.commit()
