"""منطق اصلی پخش: پیوستن به کال، مدیریت پنل و بروزرسانی خودکار نوار پیشرفت."""
import asyncio
import logging
import os
from typing import Dict, Optional

from pyrogram.errors import MessageNotModified
from pyrogram.types import InputMediaAnimation, InputMediaPhoto
from pytgcalls.types import AudioQuality, MediaStream, VideoQuality

from bot import app, call
from bot import database as db
from bot import logs
from bot import panel as panel_mod
from bot import panel_video
from bot import playlist_page
from bot import queue as q
from bot import sleep_timer
from bot import soundcloud
from bot import ui
from bot import youtube
from bot.panel import (
    cover_file,
    cover_is_animation,
    cover_static_file,
    panel_entities,
    panel_keyboard,
    panel_text,
)
from bot.queue import Track

LOGGER = logging.getLogger("musicbot.player")

PROGRESS_INTERVAL = 6

DOWNLOAD_DIR = os.environ.get(
    "DOWNLOAD_DIR",
    "/data/downloads",
).strip() or "/data/downloads"

_panel_msg: Dict[int, int] = {}
_panel_media: Dict[int, str] = {}
_panel_sig: Dict[int, str] = {}
_updater: Dict[int, asyncio.Task] = {}
_volume: Dict[int, int] = {}
_muted: Dict[int, bool] = {}

_cover_fid: Dict[str, str] = {}

# file_id عکس پروفایل ربات
_bot_profile_fid: Optional[str] = None


def _load_cover_fids() -> None:
    """بارگذاری file_idهای ذخیره‌شده از دیتابیس."""
    for key in ("anim", "static", "photo"):
        v = db.get_setting(f"cover_fid_{key}")
        if v:
            _cover_fid[key] = v


def _save_cover_fid(key: str, fid: str) -> None:
    _cover_fid[key] = fid
    try:
        db.set_setting(f"cover_fid_{key}", fid)
    except Exception:
        pass


def _cover_ref(key: str, path: str) -> str:
    """اگر file_id کش‌شده داریم همان را برگردان."""
    return _cover_fid.get(key) or path


async def _get_bot_profile_photo() -> Optional[str]:
    """گرفتن file_id عکس پروفایل فعلی ربات."""
    global _bot_profile_fid

    if _bot_profile_fid:
        return _bot_profile_fid

    try:
        async for photo in app.get_chat_photos("me", limit=1):
            if photo and photo.file_id:
                _bot_profile_fid = photo.file_id
                return _bot_profile_fid
    except Exception as e:
        LOGGER.debug("گرفتن عکس پروفایل ربات ناموفق: %s", e)

    return None


def get_volume(chat_id: int) -> int:
    return _volume.get(chat_id, 100)


def set_volume(chat_id: int, vol: int) -> None:
    _volume[chat_id] = max(0, min(200, vol))


def is_muted(chat_id: int) -> bool:
    return _muted.get(chat_id, False)


def set_muted(chat_id: int, val: bool) -> None:
    _muted[chat_id] = val


# ---------------------------------------------------------------- تایمر خواب

def sleep_left(chat_id: int):
    """ثانیه باقی‌مانده تایمر خواب."""
    return sleep_timer.left(chat_id)


def sleep_start(chat_id: int, minutes: int) -> float:
    return sleep_timer.start(chat_id, minutes)


def sleep_cancel(chat_id: int) -> bool:
    return sleep_timer.cancel(chat_id)


async def _on_sleep_expire(chat_id: int) -> None:
    """پایان تایمر خواب."""
    LOGGER.info("تایمر خواب سر رسید — پایان پخش (chat=%s)", chat_id)

    try:
        await stop(chat_id)
    except Exception as e:
        LOGGER.warning("stop در پایان تایمر خواب: %s", e)

    t = ui.Text().title(
        ui.EMO_BELL,
        ui.BASE_ARROW,
        "تایمر خواب",
    )
    t.line(
        0,
        "زمان تعیین‌شده تمام شد؛ پخش پایان یافت و از ویس‌چت خارج شدم.",
    )
    t.italic("شب خوش.")

    try:
        await app.send_message(
            chat_id,
            t.text,
            entities=t.entities,
        )
    except Exception as e:
        LOGGER.debug("پیام پایان تایمر خواب: %s", e)


sleep_timer.set_expire_handler(_on_sleep_expire)


def _stream(track: Track) -> MediaStream:
    """ساخت MediaStream."""
    src = track.local_path or track.stream_url

    if track.is_video:
        return MediaStream(
            src,
            audio_parameters=AudioQuality.HIGH,
            video_parameters=VideoQuality.HD_720p,
        )

    return MediaStream(
        src,
        audio_parameters=AudioQuality.HIGH,
        video_flags=MediaStream.Flags.IGNORE,
    )


async def _play_stream(chat_id: int, track: Track):
    """اجرای منبع پخش."""
    if track.source == "telegram_stream":
        from bot import assistant
        from bot import telegram_stream as tgs

        msg = await assistant.get_messages(
            track.tg_chat_id,
            track.tg_msg_id,
        )

        if not msg:
            raise RuntimeError(
                "پیام فایل یافت نشد (یوزربات در گروه عضو است؟)"
            )

        stream = await tgs.build_stream(
            chat_id,
            msg,
        )

        logs.info(
            "TG STREAM | %s (استریم مستقیم ۳۶۰p، بدون دانلود)",
            track.title,
        )

        await call.play(
            chat_id,
            stream,
        )
    else:
        await call.play(
            chat_id,
            _stream(track),
        )


async def _ensure_local_file(track: Track) -> bool:
    """آماده‌سازی منبع پخش."""

    if track.source == "telegram_stream":
        return bool(
            track.tg_chat_id and
            track.tg_msg_id
        )

    if track.source == "searchbot":
        if (
            track.local_path and
            os.path.isfile(track.local_path)
        ):
            if not getattr(track, "_archived", False):
                track._archived = True
                asyncio.create_task(
                    _archive_searchbot(track)
                )
            return True

        try:
            from bot import searchbot

            got = await searchbot.fetch(
                track.query or track.title
            )

            if (
                got and
                got.get("path") and
                os.path.isfile(got["path"])
            ):
                track.local_path = got["path"]
                track.stream_url = got["path"]
                return True

        except Exception as e:
            logs.debug(
                "searchbot refetch: %s",
                e,
            )

        return False

    if track.source == "archive":
        if (
            track.local_path and
            os.path.isfile(track.local_path)
        ):
            return True

        try:
            from bot import channel

            rec = getattr(
                track,
                "_archive_rec",
                None,
            )

            if rec is None:
                rec = channel.archive_lookup(
                    video_id=track.video_id,
                    query=(
                        track.query or
                        track.title
                    ),
                )

            if rec:
                path = await channel.archive_download(
                    rec,
                    DOWNLOAD_DIR,
                )

                if (
                    path and
                    os.path.isfile(path)
                ):
                    track.local_path = path

                    logs.info(
                        "ARCHIVE HIT | %s (از کانال، بدون دانلود)",
                        track.title,
                    )

                    return True

        except Exception as e:
            logs.debug(
                "archive source: %s",
                e,
            )

        return False

    if track.source == "soundcloud":
        try:
            from bot import channel

            rec = channel.archive_lookup(
                query=(
                    track.query or
                    track.title
                ),
            )

            if rec:
                path = await channel.archive_download(
                    rec,
                    DOWNLOAD_DIR,
                )

                if (
                    path and
                    os.path.isfile(path)
                ):
                    track.local_path = path
                    track.source = "archive"

                    logs.info(
                        "ARCHIVE HIT | %s (ساوندکلاد از کانال)",
                        track.title,
                    )

                    return True

        except Exception as e:
            logs.debug(
                "sc archive lookup: %s",
                e,
            )

        if track.query:
            try:
                fresh = await soundcloud.search(
                    track.query
                )

                if (
                    fresh and
                    fresh.get("stream_url")
                ):
                    track.stream_url = (
                        fresh["stream_url"]
                    )

            except Exception as e:
                logs.debug(
                    "sc refresh: %s",
                    e,
                )

        if (
            track.query and
            not getattr(track, "_archived", False)
        ):
            track._archived = True

            asyncio.create_task(
                _archive_soundcloud(track)
            )

        return bool(track.stream_url)

    if (
        track.local_path and
        os.path.isfile(track.local_path)
    ):
        return True

    vid = getattr(
        track,
        "video_id",
        "",
    ) or ""

    if vid:
        cached = db.cache_get(vid)

        if (
            cached and
            os.path.isfile(cached["path"])
        ):
            track.local_path = cached["path"]

            logs.info(
                "CACHE HIT | %s (بدون دانلود دوباره)",
                track.title,
            )

            return True

    try:
        from bot import channel

        rec = channel.archive_lookup(
            video_id=vid,
            query=(
                track.query or
                track.title
            ),
        )

        if rec:
            path = await channel.archive_download(
                rec,
                DOWNLOAD_DIR,
            )

            if (
                path and
                os.path.isfile(path)
            ):
                track.local_path = path
                track.source = "archive"

                logs.info(
                    "ARCHIVE HIT | %s (از کانال، بدون یوتیوب)",
                    track.title,
                )

                if vid:
                    db.cache_put(
                        vid,
                        path,
                        rec.get(
                            "title",
                            track.title,
                        ),
                        int(
                            rec.get("duration") or
                            0
                        ),
                        track.is_video,
                    )

                    _prune_cache()

                return True

    except Exception as e:
        logs.debug(
            "archive lookup: %s",
            e,
        )

    query = (
        track.query or
        track.webpage_url or
        track.title
    )

    try:
        with logs.stage(
            "DOWNLOAD",
            title=track.title,
            video=track.is_video,
        ):
            info = await youtube.download_media(
                query,
                video=track.is_video,
                out_dir=DOWNLOAD_DIR,
            )

        path = info.get(
            "path",
            "",
        )

        if (
            path and
            os.path.isfile(path)
        ):
            track.local_path = path

            vid = (
                info.get("id") or
                vid
            )

            if vid:
                track.video_id = vid

                db.cache_put(
                    vid,
                    path,
                    info.get(
                        "title",
                        track.title,
                    ),
                    int(
                        info.get("duration") or
                        0
                    ),
                    track.is_video,
                )

                _prune_cache()

            try:
                from bot import channel

                asyncio.create_task(
                    channel.archive_store(
                        path,
                        vid,
                        query,
                        info.get(
                            "title",
                            track.title,
                        ),
                        int(
                            info.get("duration") or
                            0
                        ),
                        track.is_video,
                        source=(
                            track.source or
                            "youtube"
                        ),
                        url=(
                            track.webpage_url or
                            ""
                        ),
                        added_by=(
                            track.requester_id or
                            0
                        ),
                    )
                )

            except Exception as e:
                logs.debug(
                    "archive store schedule: %s",
                    e,
                )

            return True

        logs.warn(
            "DOWNLOAD: فایل ساخته نشد | %s",
            track.title,
        )

        return False

    except Exception as e:
        logs.warn(
            "DOWNLOAD error | %s: %s",
            track.title,
            e,
        )

        return False


def _prune_cache() -> None:
    """فقط فایل‌های اخیر کش را نگه می‌دارد."""
    keep = int(
        os.environ.get(
            "CACHE_KEEP",
            "10",
        )
    )

    try:
        for path in db.cache_prune(
            keep=keep
        ):
            try:
                if (
                    path and
                    os.path.isfile(path)
                ):
                    os.remove(path)

                    logs.info(
                        "CACHE PRUNE | حذف %s",
                        os.path.basename(path),
                    )

            except OSError:
                pass

    except Exception as e:
        logs.debug(
            "prune cache: %s",
            e,
        )


async def _archive_searchbot(track: Track) -> None:
    """آرشیو آهنگ جستجو شده."""
    try:
        from bot import channel
        import config

        if not config.ARCHIVE_CHANNEL:
            return

        path = track.local_path

        if (
            not path or
            not os.path.isfile(path)
        ):
            return

        q_text = (
            track.query or
            track.title
        )

        if (
            channel.archive_lookup(
                query=q_text
            ) or
            channel.archive_lookup(
                query=track.title
            )
        ):
            return

        await channel.publish_song(
            app,
            path,
            title=track.title,
            performer=(
                getattr(
                    track,
                    "performer",
                    "",
                ) or ""
            ),
            duration=int(
                track.duration or
                0
            ),
            source="searchbot",
            added_by=(
                track.requester_id or
                0
            ),
            is_video=False,
            key=channel._norm_key(
                "",
                track.title,
            ),
        )

    except Exception as e:
        logs.debug(
            "archive searchbot: %s",
            e,
        )


async def _archive_soundcloud(track: Track) -> None:
    """آرشیو ساوندکلاد."""
    try:
        from bot import channel
        import config

        if not config.ARCHIVE_CHANNEL:
            return

        if channel.archive_lookup(
            query=(
                track.query or
                track.title
            )
        ):
            return

        info = await soundcloud.download(
            track.query,
            out_dir=DOWNLOAD_DIR,
        )

        path = info.get(
            "path",
            "",
        )

        if (
            path and
            os.path.isfile(path)
        ):
            await channel.archive_store(
                path,
                "",
                track.query,
                info.get(
                    "title",
                    track.title,
                ),
                int(
                    info.get("duration") or
                    0
                ),
                False,
                source="soundcloud",
                url=(
                    track.webpage_url or
                    ""
                ),
                added_by=(
                    track.requester_id or
                    0
                ),
            )

            try:
                os.remove(path)
            except OSError:
                pass

    except Exception as e:
        logs.debug(
            "archive soundcloud: %s",
            e,
        )


def _cleanup_orphans() -> None:
    """پاک‌سازی فایل‌های یتیم."""
    try:
        d = DOWNLOAD_DIR

        if not os.path.isdir(d):
            return

        max_mb = int(
            os.environ.get(
                "DOWNLOAD_MAX_MB",
                "350",
            )
        )

        min_age = int(
            os.environ.get(
                "ORPHAN_MIN_AGE",
                "1800",
            )
        )

        import time as _t

        now = _t.time()
        protected = set()

        for t in q._now_playing.values():
            if t.local_path:
                protected.add(
                    os.path.abspath(
                        t.local_path
                    )
                )

        try:
            for p in db.cache_paths():
                protected.add(
                    os.path.abspath(p)
                )
        except Exception:
            pass

        entries = []
        total = 0

        for name in os.listdir(d):
            p = os.path.abspath(
                os.path.join(
                    d,
                    name,
                )
            )

            if not os.path.isfile(p):
                continue

            try:
                st = os.stat(p)
            except OSError:
                continue

            total += st.st_size

            entries.append(
                (
                    p,
                    st.st_size,
                    st.st_mtime,
                )
            )

        for p, size, mtime in entries:
            if (
                p in protected or
                now - mtime < min_age
            ):
                continue

            try:
                os.remove(p)
                total -= size

                logs.info(
                    "ORPHAN CLEANUP | حذف %s",
                    os.path.basename(p),
                )

            except OSError:
                pass

        if total > max_mb * 1024 * 1024:
            for p, size, mtime in sorted(
                entries,
                key=lambda e: e[2],
            ):
                if (
                    p in protected or
                    not os.path.isfile(p)
                ):
                    continue

                try:
                    os.remove(p)
                    total -= size

                    logs.info(
                        "DISK CAP | حذف %s",
                        os.path.basename(p),
                    )

                except OSError:
                    pass

                if total <= max_mb * 1024 * 1024:
                    break

    except Exception as e:
        LOGGER.debug(
            "cleanup orphans: %s",
            e,
        )


def _source_ready(track: Track) -> bool:
    """آیا منبع پخش آماده است؟"""
    if track.source == "telegram_stream":
        return bool(
            track.tg_chat_id and
            track.tg_msg_id
        )

    if track.local_path:
        return os.path.isfile(
            track.local_path
        )

    return bool(track.stream_url)


async def start_playback(
    chat_id: int,
    track: Track,
) -> None:
    ok = await _ensure_local_file(
        track
    )

    if (
        not ok or
        not _source_ready(track)
    ):
        logs.warn(
            "PLAY SKIP | منبع آماده نیست: %s",
            track.title,
        )

        nxt = q.pop_next(chat_id)

        if nxt is not None:
            await start_playback(
                chat_id,
                nxt,
            )
        else:
            await stop(chat_id)

        return

    q.set_now_playing(
        chat_id,
        track,
    )

    await _play_stream(
        chat_id,
        track,
    )

    await _send_panel(
        chat_id,
        new=True,
    )


async def play_or_queue(
    chat_id: int,
    track: Track,
) -> int:
    if q.now_playing(chat_id) is None:
        await start_playback(
            chat_id,
            track,
        )
        return 0

    return q.add(
        chat_id,
        track,
    )


async def resume_after_restart(
    chat_id: int,
    track: Track,
) -> None:
    """ادامه پخش بعد از ری‌استارت."""
    try:
        track.mark_started()

        if track.source == "telegram_stream":
            LOGGER.info(
                "resume: رد استریم تلگرام: %s",
                track.title,
            )

            q.clear(chat_id)
            return

        ok = await _ensure_local_file(
            track
        )

        if (
            not ok or
            not _source_ready(track)
        ):
            LOGGER.info(
                "resume: منبع آماده نیست: %s",
                track.title,
            )

            q.clear(chat_id)
            return

        await call.play(
            chat_id,
            _stream(track),
        )

        await _send_panel(
            chat_id,
            new=True,
        )

    except Exception as e:
        LOGGER.warning(
            "resume_after_restart chat=%s: %s",
            chat_id,
            e,
        )

        raise


async def skip(
    chat_id: int,
) -> Optional[Track]:
    _stop_tg_stream(chat_id)

    nxt = q.pop_next(chat_id)

    if nxt is None:
        await end_playback(
            chat_id
        )
        return None

    ok = await _ensure_local_file(
        nxt
    )

    if (
        not ok or
        not _source_ready(nxt)
    ):
        logs.warn(
            "SKIP SKIP | منبع آماده نیست: %s → بعدی",
            nxt.title,
        )

        return await skip(
            chat_id
        )

    await _play_stream(
        chat_id,
        nxt,
    )

    await _send_panel(
        chat_id,
        new=True,
    )

    return nxt


async def previous(
    chat_id: int,
) -> Optional[Track]:
    _stop_tg_stream(chat_id)

    prev = q.pop_previous(
        chat_id
    )

    if prev is None:
        return None

    ok = await _ensure_local_file(
        prev
    )

    if (
        not ok or
        not _source_ready(prev)
    ):
        logs.warn(
            "PREV SKIP | منبع آماده نیست: %s",
            prev.title,
        )

        return None

    await _play_stream(
        chat_id,
        prev,
    )

    await _send_panel(
        chat_id,
        new=True,
    )

    return prev


async def repeat_current(
    chat_id: int,
) -> None:
    """تکرار آهنگ فعلی."""
    cur = q.now_playing(
        chat_id
    )

    if cur is None:
        await stop(chat_id)
        return

    _stop_tg_stream(chat_id)

    cur.mark_started()

    ok = await _ensure_local_file(
        cur
    )

    if (
        not ok or
        not _source_ready(cur)
    ):
        await skip(chat_id)
        return

    await _play_stream(
        chat_id,
        cur,
    )

    await _send_panel(
        chat_id,
        new=True,
    )


async def play_random(
    chat_id: int,
) -> None:
    """پخش تصادفی از آرشیو."""
    from bot import channel

    rec = db.archive_random(
        audio_only=True
    )

    if not rec:
        logs.warn(
            "RANDOM | آرشیو خالی است chat=%s",
            chat_id,
        )

        await stop(chat_id)
        return

    path = await channel.archive_download(
        rec,
        DOWNLOAD_DIR,
    )

    if (
        not path or
        not os.path.isfile(path)
    ):
        logs.warn(
            "RANDOM | دانلود از آرشیو ناموفق"
        )

        await stop(chat_id)
        return

    track = Track(
        title=rec.get(
            "title",
            "آهنگ تصادفی",
        ),
        stream_url=path,
        webpage_url="",
        duration=int(
            rec.get("duration") or
            0
        ),
        duration_text=_fmt_dur_int(
            int(
                rec.get("duration") or
                0
            )
        ),
        thumbnail=None,
        requester="پخش رندوم",
        is_video=False,
        query="",
        video_id="",
        source="archive",
    )

    track.local_path = path

    q.set_now_playing(
        chat_id,
        track,
    )

    await call.play(
        chat_id,
        _stream(track),
    )

    await _send_panel(
        chat_id,
        new=True,
    )


def _fmt_dur_int(
    seconds: int,
) -> str:
    if not seconds:
        return "نامشخص"

    m, s = divmod(
        int(seconds),
        60,
    )

    h, m = divmod(
        m,
        60,
    )

    if h:
        return f"{h}:{m:02d}:{s:02d}"

    return f"{m}:{s:02d}"


def _stop_tg_stream(
    chat_id: int,
) -> None:
    """توقف استریم مستقیم تلگرام."""
    try:
        from bot import telegram_stream as tgs

        tgs.stop_previous(
            chat_id
        )

    except Exception as e:
        logs.debug(
            "stop tg stream: %s",
            e,
        )


async def stop(
    chat_id: int,
) -> None:
    _stop_tg_stream(chat_id)

    q.clear(chat_id)

    _cancel_updater(
        chat_id
    )

    _muted.pop(
        chat_id,
        None,
    )

    _panel_sig.pop(
        chat_id,
        None,
    )

    panel_mod.reset_menus(
        chat_id
    )

    sleep_timer.cancel(
        chat_id
    )

    await _delete_panel(
        chat_id
    )

    try:
        await call.leave_call(
            chat_id
        )

    except Exception as e:
        LOGGER.warning(
            "leave_call: %s",
            e,
        )


async def end_playback(
    chat_id: int,
) -> None:
    """پایان طبیعی صف."""
    _stop_tg_stream(chat_id)

    q.end_current(
        chat_id
    )

    _cancel_updater(
        chat_id
    )

    _muted.pop(
        chat_id,
        None,
    )

    _panel_sig.pop(
        chat_id,
        None,
    )

    panel_mod.reset_menus(
        chat_id
    )

    sleep_timer.cancel(
        chat_id
    )

    await _delete_panel(
        chat_id
    )

    try:
        await call.leave_call(
            chat_id
        )

    except Exception as e:
        LOGGER.warning(
            "leave_call: %s",
            e,
        )


# --------------------------------------------------------- پنل

async def _send_panel(
    chat_id: int,
    new: bool = False,
) -> None:
    """ارسال پنل آهنگ با دکمه‌های کنترل.

    اگر کاور اختصاصی وجود داشته باشد همان استفاده می‌شود.
    اگر کاور وجود نداشته باشد، عکس پروفایل ربات استفاده می‌شود.
    """

    track = q.now_playing(
        chat_id
    )

    if track is None:
        return

    await _delete_panel(
        chat_id
    )

    panel_mod.reset_menus(
        chat_id
    )

    text, ents, kb = _render(
        chat_id,
        track,
    )

    cover = cover_file()
    static = cover_static_file()

    # اگر کاور اختصاصی نداریم، عکس پروفایل ربات را بگیر
    profile_photo = None

    if not cover and not static:
        profile_photo = (
            await _get_bot_profile_photo()
        )

    try:
        # آهنگ در حالت مکث
        if track.paused:
            if static:
                msg = await app.send_photo(
                    chat_id,
                    _cover_ref(
                        "static",
                        static,
                    ),
                    caption=text,
                    caption_entities=ents,
                    reply_markup=kb,
                )

                _panel_media[chat_id] = "static"

                if (
                    msg.photo and
                    "static" not in _cover_fid
                ):
                    _save_cover_fid(
                        "static",
                        msg.photo.file_id,
                    )

            elif profile_photo:
                msg = await app.send_photo(
                    chat_id,
                    profile_photo,
                    caption=text,
                    caption_entities=ents,
                    reply_markup=kb,
                )

                _panel_media[chat_id] = "profile"

            else:
                msg = await app.send_message(
                    chat_id,
                    text,
                    entities=ents,
                    reply_markup=kb,
                )

                _panel_media[chat_id] = "text"

        # کاور متحرک اختصاصی
        elif (
            cover and
            cover_is_animation()
        ):
            msg = await app.send_animation(
                chat_id,
                _cover_ref(
                    "anim",
                    cover,
                ),
                caption=text,
                caption_entities=ents,
                reply_markup=kb,
            )

            _panel_media[chat_id] = "anim"

            if (
                msg.animation and
                "anim" not in _cover_fid
            ):
                _save_cover_fid(
                    "anim",
                    msg.animation.file_id,
                )

        # کاور عکس اختصاصی
        elif cover:
            msg = await app.send_photo(
                chat_id,
                _cover_ref(
                    "photo",
                    cover,
                ),
                caption=text,
                caption_entities=ents,
                reply_markup=kb,
            )

            _panel_media[chat_id] = "photo"

            if (
                msg.photo and
                "photo" not in _cover_fid
            ):
                _save_cover_fid(
                    "photo",
                    msg.photo.file_id,
                )

        # عکس پروفایل خود ربات
        elif profile_photo:
            msg = await app.send_photo(
                chat_id,
                profile_photo,
                caption=text,
                caption_entities=ents,
                reply_markup=kb,
            )

            _panel_media[chat_id] = "profile"

        # اگر عکس پروفایل هم موجود نبود
        else:
            msg = await app.send_message(
                chat_id,
                text,
                entities=ents,
                reply_markup=kb,
            )

            _panel_media[chat_id] = "text"

        _panel_msg[chat_id] = msg.id

    except Exception as e:
        LOGGER.warning(
            "ارسال پنل ناموفق، بازگشت به متن: %s",
            e,
        )

        try:
            msg = await app.send_message(
                chat_id,
                text,
                entities=ents,
                reply_markup=kb,
            )

            _panel_msg[chat_id] = msg.id
            _panel_media[chat_id] = "text"

        except Exception as e2:
            LOGGER.error(
                "ارسال پنل کاملاً ناموفق: %s",
                e2,
            )

            return

    _start_updater(
        chat_id
    )


async def _delete_panel(
    chat_id: int,
) -> None:
    mid = _panel_msg.pop(
        chat_id,
        None,
    )

    _panel_media.pop(
        chat_id,
        None,
    )

    _panel_sig.pop(
        chat_id,
        None,
    )

    if mid:
        try:
            await app.delete_messages(
                chat_id,
                mid,
            )
        except Exception:
            pass


def _render(
    chat_id: int,
    track: Track,
):
    """ساخت متن و دکمه‌های پنل."""
    vol = get_volume(chat_id)
    muted = is_muted(chat_id)

    # پنل فیلم دست‌نخورده
    if track.is_video:
        text, ents = panel_video.content(
            track,
            vol,
            muted,
            chat_id,
        )

        return (
            text,
            ents,
            panel_video.keyboard(
                chat_id,
                track,
                vol,
                muted,
                sleep_left(chat_id),
            ),
        )

    # صفحه صف
    if (
        panel_mod.get_view(chat_id) ==
        panel_mod.VIEW_PLAYLIST
    ):
        items = list(
            q.get_queue(chat_id)
        )

        page = playlist_page.clamp_page(
            panel_mod.get_view_page(
                chat_id
            ),
            len(items),
        )

        if (
            page !=
            panel_mod.get_view_page(
                chat_id
            )
        ):
            panel_mod.set_view(
                chat_id,
                panel_mod.VIEW_PLAYLIST,
                page,
            )

        text, ents = playlist_page.content(
            track,
            items,
            page,
        )

        return (
            text,
            ents,
            playlist_page.keyboard(
                items,
                page,
            ),
        )

    # پنل اصلی پخش + همه دکمه‌های فعلی
    return (
        panel_text(
            track,
            vol,
            muted,
            chat_id,
        ),
        panel_entities(
            track,
            vol,
            muted,
            chat_id,
        ),
        panel_keyboard(
            chat_id,
            track,
            vol,
            muted,
            sleep_left(chat_id),
        ),
    )


async def refresh_panel(
    chat_id: int,
    force: bool = False,
) -> None:
    """بروزرسانی پنل و نوار پیشرفت."""

    track = q.now_playing(
        chat_id
    )

    mid = _panel_msg.get(
        chat_id
    )

    if (
        track is None or
        mid is None
    ):
        return

    text, ents, kb = _render(
        chat_id,
        track,
    )

    sig = ui.signature(
        text,
        kb,
    )

    if (
        not force and
        _panel_sig.get(chat_id) == sig
    ):
        return

    anim = cover_file()
    static = cover_static_file()

    # اگر کاور اختصاصی نیست، پروفایل ربات استفاده می‌شود
    has_profile = (
        not anim and
        not static and
        bool(_bot_profile_fid)
    )

    want_static = (
        track.paused and
        bool(static)
    )

    if want_static:
        desired = "static"
    elif anim and cover_is_animation():
        desired = "anim"
    elif anim:
        desired = "photo"
    elif has_profile:
        desired = "profile"
    else:
        desired = "text"

    current = _panel_media.get(
        chat_id
    )

    try:
        if (
            desired in (
                "static",
                "anim",
            ) and
            desired != current
        ):
            if desired == "static":
                media = InputMediaPhoto(
                    _cover_ref(
                        "static",
                        static,
                    ),
                    caption=text,
                    caption_entities=ents,
                )

            else:
                media = InputMediaAnimation(
                    _cover_ref(
                        "anim",
                        anim,
                    ),
                    caption=text,
                    caption_entities=ents,
                )

            await app.edit_message_media(
                chat_id,
                mid,
                media=media,
                reply_markup=kb,
            )

            _panel_media[chat_id] = desired

        elif desired == "profile" and current != "profile":
            # برای تعویض به عکس پروفایل، پیام رسانه‌ای قبلی را حذف
            # و پنل را دوباره با عکس پروفایل ارسال می‌کنیم.
            await app.delete_messages(
                chat_id,
                mid,
            )

            new_mid = await app.send_photo(
                chat_id,
                _bot_profile_fid,
                caption=text,
                caption_entities=ents,
                reply_markup=kb,
            )

            _panel_msg[chat_id] = new_mid.id
            _panel_media[chat_id] = "profile"

        elif desired in (
            "anim",
            "static",
            "photo",
        ):
            await app.edit_message_caption(
                chat_id,
                mid,
                caption=text,
                caption_entities=ents,
                reply_markup=kb,
            )

        elif desired == "profile":
            await app.edit_message_caption(
                chat_id,
                mid,
                caption=text,
                caption_entities=ents,
                reply_markup=kb,
            )

        else:
            await app.edit_message_text(
                chat_id,
                mid,
                text,
                entities=ents,
                reply_markup=kb,
            )

        _panel_sig[chat_id] = sig

    except MessageNotModified:
        _panel_sig[chat_id] = sig

    except Exception as e:
        LOGGER.debug(
            "refresh_panel: %s",
            e,
        )


def _start_updater(
    chat_id: int,
) -> None:
    _cancel_updater(
        chat_id
    )

    _updater[chat_id] = asyncio.create_task(
        _progress_loop(chat_id)
    )


def _cancel_updater(
    chat_id: int,
) -> None:
    task = _updater.pop(
        chat_id,
        None,
    )

    if (
        task and
        not task.done()
    ):
        task.cancel()


async def _progress_loop(
    chat_id: int,
) -> None:
    """بروزرسانی نوار پیشرفت."""
    try:
        while True:
            await asyncio.sleep(
                PROGRESS_INTERVAL
            )

            track = q.now_playing(
                chat_id
            )

            if track is None:
                break

            if track.paused:
                continue

            await refresh_panel(
                chat_id
            )

            if (
                track.duration and
                track.position() >=
                track.duration
            ):
                break

    except asyncio.CancelledError:
        pass

    except Exception as e:
        LOGGER.debug(
            "progress_loop: %s",
            e,
        )


def panel_message_id(
    chat_id: int,
) -> Optional[int]:
    return _panel_msg.get(
        chat_id
    )
