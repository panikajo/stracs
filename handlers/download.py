import asyncio
import os
import re
import html
import inspect
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from database.db import (
    can_download, record_download, use_extra_download,
    get_setting, get_user_language, get_user_download_mode, get_user_settings,
    get_group_settings, ensure_group_chat,
)
from services.platform import detect_platform, get_platform_info
from services.downloader import download, get_info, cleanup_file, DownloadResult

# Some deployed versions of services/downloader.py do not yet contain gallery /
# slideshow helpers. Keep handlers/download.py backward-compatible so the bot can
# start even before those optional helpers are added.
try:
    from services.downloader import (
        download_gallery, build_slideshow, cleanup_gallery, is_photo_post, GalleryResult,
    )
except ImportError:
    class GalleryResult:  # fallback only for type annotations
        pass

    def is_photo_post(info):
        return False

    async def download_gallery(*args, **kwargs):
        return None

    async def build_slideshow(*args, **kwargs):
        return None

    def cleanup_gallery(gallery):
        pass


async def _download_compat(url: str, platform: str, *, audio_only: bool = False, quality: str = "480", watermark: bool = False):
    """Call services.downloader.download with only supported keyword args.

    Some deployed downloader.py versions do not support the newer `watermark`
    option. Introspect the real function so handlers/download.py remains
    backward-compatible instead of crashing with unexpected keyword argument.
    """
    kwargs = {"audio_only": audio_only, "quality": quality}
    try:
        sig = inspect.signature(download)
        params = sig.parameters
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        if accepts_kwargs or "watermark" in params:
            kwargs["watermark"] = watermark
    except Exception:
        # If signature inspection fails, use the conservative old API.
        pass
    return await download(url, platform, **kwargs)

from aiogram.types import InputMediaPhoto, InputMediaVideo
from services.limiter import is_downloading, set_active, clear_active, cancel_download
from keyboards.inline import quality_keyboard, cancel_keyboard
from config import config
from services.url_store import store_url, get_url
from services.bulk_stories import get_stories_list
from services.i18n import t

router = Router()


# Bot username used in the "Via" credit line. Override via env if needed.
BOT_USERNAME = os.getenv("BOT_USERNAME", "tikloadtokbot")
VIA_START_PARAM = os.getenv("VIA_START_PARAM", "c")



def _normalize_threads_url(url: str) -> str:
    """Normalize Slack/Threads URLs before platform detection and yt-dlp.

    yt-dlp may not recognize threads.com or Slack-style <url> wrappers.
    Convert to the canonical threads.net post URL and drop tracking params.
    """
    if not url:
        return url
    u = str(url).strip().strip("<>").strip()
    # Slack sometimes stores <url|label>; keep only URL part.
    if u.startswith("http") and "|" in u:
        u = u.split("|", 1)[0].strip("<>")
    m = re.search(r"https?://(?:www\.)?threads\.(?:com|net)/(@[^/]+)/(post|media)/([^/?#>]+)", u, re.I)
    if m:
        user, kind, post_id = m.groups()
        return f"https://www.threads.net/{user}/{kind}/{post_id}"
    return u


def _platform_label(platform: str) -> str:
    return {
        "youtube": "YouTube",
        "instagram": "Instagram",
        "tiktok": "TikTok",
        "threads": "Threads",
    }.get(platform, "Джерело")


def _clean_author_login(value) -> str:
    """Return a safe @username candidate, or empty string if it looks like an ID.

    TikTok / yt-dlp can return a numeric internal author id in `uploader_id`
    (example: 7332883848974812165). That must not be displayed as @nickname.
    Prefer human-readable fields and reject pure numeric IDs / URLs / names with
    spaces.
    """
    if value is None:
        return ""
    value = str(value).strip().lstrip("@")
    if not value:
        return ""
    if value.isdigit():
        return ""
    if value.startswith(("http://", "https://")):
        return ""
    if len(value) > 30:
        return ""
    # TikTok/Instagram usernames are normally latin letters, digits, dot,
    # underscore. Reject display names with spaces/emojis.
    if not re.fullmatch(r"[A-Za-z0-9._]{2,30}", value):
        return ""
    return value


def _author_login(result) -> str:
    """Best-effort source username for captions.

    Order matters: `uploader_id` is often an internal numeric TikTok id, so it is
    checked only after friendlier fields and still validated.
    """
    for field in ("uploader", "channel", "creator", "artist", "uploader_id", "channel_id"):
        login = _clean_author_login(getattr(result, field, None))
        if login:
            return login

    # Last chance: extract username from the source URL itself.
    source_url = getattr(result, "source_url", "") or ""
    platform = getattr(result, "platform", "")
    if platform == "tiktok":
        # TikTok author URLs are /@username/..., do not treat /video/... as a username.
        m = re.search(r"tiktok\.com/@([A-Za-z0-9._]{2,30})(?:/|$)", source_url)
    elif platform == "instagram":
        # Instagram post URLs like /p/... or /reel/... are not usernames.
        m = re.search(r"instagram\.com/(?!p/|reel/|tv/|stories/|explore/)([A-Za-z0-9._]{2,30})(?:/|$)", source_url)
    elif platform == "threads":
        m = re.search(r"threads\.(?:net|com)/@([A-Za-z0-9._]{2,30})(?:/|$)", source_url)
    else:
        m = None
    if m:
        return _clean_author_login(m.group(1))
    return ""


def _author_url(result) -> str:
    """Best-effort link to the content author's profile."""
    login = _author_login(result)
    platform = getattr(result, "platform", "")
    if login:
        if platform == "tiktok":
            return f"https://www.tiktok.com/@{login}"
        if platform == "instagram":
            return f"https://instagram.com/{login}"
        if platform == "threads":
            return f"https://www.threads.net/@{login}"
    # Fallback: the post link itself.
    return getattr(result, "source_url", "") or ""


def _chat_url(chat) -> str:
    """Public Telegram URL for a sender_chat/channel, if Telegram exposes one."""
    if chat is None:
        return ""
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}"
    return ""


def _chat_title(chat) -> str:
    if chat is None:
        return ""
    return getattr(chat, "title", None) or getattr(chat, "full_name", None) or getattr(chat, "username", None) or "Via"


def _message_via_chat(message):
    """If a message was sent as a group/channel, use that chat as Via."""
    return getattr(message, "sender_chat", None) if message is not None else None


def _message_via_user(message):
    """Use the real user unless Telegram only gives GroupAnonymousBot."""
    if message is None:
        return None
    user = getattr(message, "from_user", None)
    if not user:
        return None
    if getattr(user, "username", None) == "GroupAnonymousBot":
        return None
    return user


def _clean_source_description(text: str) -> str:
    """Remove extractor junk like a bare numeric TikTok author id."""
    if not text:
        return ""
    cleaned = []
    for line in str(text).splitlines():
        stripped = line.strip()
        if re.fullmatch(r"@?\d{8,}", stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def build_caption(result, via_user=None, via_chat=None, show_tags=False, show_source_channel=False,
                  caption_mode="src_via", desc_mode="off") -> str:
    """Build the Telegram HTML caption for a finished download.

    caption_mode — the credit line under the content:
        src_via  → 🎬 Джерело ✦ Via (author)   [default]
        src      → 🎬 Джерело
        src_plus → 🎬 Джерело   (reserved for a future /custom_caption suffix)
        author   → 👤 @author
        off      → no credit line

    desc_mode — how the post description/text is shown:
        off / separate → not embedded here (separate handled by caller)
        with    → appended as plain text
        quote   → appended as a <blockquote>
        country → show the upload country/geo instead of the description

    The blockquote of @login (show_source_channel) + #hashtags (show_tags) is
    layered on as before, independent of caption_mode.
    """
    source_url = result.source_url or ""

    # "Via" points to the chat/channel that sent the link when Telegram provides
    # sender_chat (anonymous admin / post as channel). Otherwise it points to the
    # real user. Never use @GroupAnonymousBot as Via.
    via_url = None
    via_text = "Via"
    if via_chat is not None:
        via_text = _chat_title(via_chat) or "Via"
        via_url = _chat_url(via_chat)
    elif via_user is not None:
        uname = getattr(via_user, "username", None)
        uid = getattr(via_user, "id", None)
        if uname and uname != "GroupAnonymousBot":
            via_url = f"https://t.me/{uname}"
        elif uid:
            via_url = f"tg://user?id={uid}"
    if not via_url and via_text == "Via":
        via_url = f"https://t.me/{BOT_USERNAME}?start={VIA_START_PARAM}"

    src_link = f'🎬 <a href="{html.escape(source_url, quote=True)}">Джерело</a>'
    if via_url:
        via_link = f'<a href="{html.escape(via_url, quote=True)}">{html.escape(via_text)}</a>'
    else:
        via_link = html.escape(via_text)

    login = _author_login(result)
    author_url = _author_url(result)
    if login:
        # Do not make the source channel clickable. Telegram auto-links plain
        # @username, so render it as <code> for tap/select/copy instead.
        author_link = f"👤 <code>@{html.escape(login)}</code>"
    elif author_url:
        author_link = f"👤 <a href=\"{html.escape(author_url, quote=True)}\">Автор</a>"
    else:
        author_link = ""

    # ─── Credit line per caption_mode ───
    if caption_mode == "off":
        line1 = ""
    elif caption_mode == "author":
        line1 = author_link
    elif caption_mode in ("src", "src_plus"):
        line1 = src_link
    else:  # src_via (default)
        line1 = f"{src_link} ✦ {via_link}"

    # ─── @login + hashtags blockquote (admin/user gated) ───
    # Skip the duplicate @login when the credit line already shows the author.
    quote_lines = []
    if show_source_channel and login and caption_mode != "author":
        # Plain @username becomes clickable in Telegram. <code> keeps it
        # non-clickable and easy to copy.
        quote_lines.append(f"📋 <code>@{html.escape(login)}</code>")
    tags = result.tags or []
    if show_tags and tags:
        tag_str = " ".join("#" + html.escape(str(t).lstrip("#")) for t in tags if t)
        if tag_str:
            quote_lines.append(tag_str)

    parts = []
    if line1:
        parts.append(line1)
    if quote_lines:
        parts.append("<blockquote>" + "\n".join(quote_lines) + "</blockquote>")

    # ─── Description / geo ───
    if desc_mode == "country":
        geo = (result.geo or "").strip()
        if geo:
            parts.append(f"🌍 {html.escape(geo)}")
    elif desc_mode in ("with", "quote"):
        desc = _clean_source_description(result.description or "")
        if desc:
            desc = html.escape(desc)
            if desc_mode == "quote":
                parts.append(f"<blockquote>{desc}</blockquote>")
            else:
                parts.append(desc)

    caption = "\n".join(parts)
    # Telegram caption hard limit is 1024 chars
    return caption[:1024]


async def _platform_enabled(platform: str) -> bool:
    key = {
        "youtube": "feature_youtube",
        "instagram": "feature_instagram",
        "tiktok": "feature_tiktok",
        "threads": "feature_threads",
    }.get(platform)
    if not key:
        return True
    return await get_setting(key, "1") == "1"


async def _effective_chat_language(chat_id: int, user_id: int) -> str:
    """Language for messages in this chat: per-group language or user language."""
    # Telegram group/supergroup/channel ids are negative. Private chats are user ids.
    if chat_id < 0:
        try:
            g = await get_group_settings(chat_id)
            if g and g.get("language"):
                return g["language"]
        except Exception:
            pass
    return await get_user_language(user_id)


async def _effective_message_language(message: Message, user_id: int) -> str:
    if message.chat.type in ("group", "supergroup", "channel"):
        g = await get_group_settings(message.chat.id)
        if g is None:
            await ensure_group_chat(
                message.chat.id, message.chat.title, message.chat.type,
                language=await get_user_language(user_id),
            )
            g = await get_group_settings(message.chat.id)
        if g and g.get("language"):
            return g["language"]
    return await get_user_language(user_id)


def _is_instagram_access_error(error: str) -> bool:
    """True for common yt-dlp Instagram login/cookie/access failures."""
    err = (error or "").lower()
    needles = (
        "empty media response",
        "without being logged-in",
        "login required",
        "please log in",
        "cookies",
        "challenge_required",
        "checkpoint_required",
        "requested content is not available",
        "unable to extract shared data",
    )
    return any(n in err for n in needles)


def _instagram_access_message(lang: str, url: str, error: str = "") -> str:
    link = html.escape(url or "", quote=True)
    if lang == "uk":
        return (
            "❌ <b>Instagram не віддав медіа.</b>\n\n"
            f"<a href=\"{link}\">Відкрити пост</a>\n\n"
            "Найчастіше причина — Instagram вимагає авторизацію або cookies застаріли. "
            "Адміну потрібно оновити Instagram cookies командою /refreshcookies і спробувати ще раз."
        )
    if lang == "en":
        return (
            "❌ <b>Instagram did not return media.</b>\n\n"
            f"<a href=\"{link}\">Open post</a>\n\n"
            "Most likely Instagram requires login or the cookies are expired. "
            "Admin should refresh Instagram cookies with /refreshcookies and try again."
        )
    return (
        "❌ <b>Instagram не отдал медиа.</b>\n\n"
        f"<a href=\"{link}\">Открыть пост</a>\n\n"
        "Чаще всего причина — Instagram требует авторизацию или cookies устарели. "
        "Админу нужно обновить Instagram cookies командой /refreshcookies и попробовать ещё раз."
    )

def _instagram_preview_fallback_text(lang: str, url: str) -> str:
    """Shown when IG metadata lookup fails, but direct download may still work."""
    link = html.escape(url or "", quote=True)
    if lang == "uk":
        return (
            "⚠️ <b>Instagram не віддав попередній перегляд.</b>\n\n"
            f"<a href=\"{link}\">Відкрити пост</a>\n\n"
            "Але це ще не означає, що скачування неможливе. Обери формат — бот спробує скачати напряму."
        )
    if lang == "en":
        return (
            "⚠️ <b>Instagram did not return preview info.</b>\n\n"
            f"<a href=\"{link}\">Open post</a>\n\n"
            "This does not always mean the reel is unavailable. Choose a format and the bot will try direct download."
        )
    return (
        "⚠️ <b>Instagram не отдал предпросмотр.</b>\n\n"
        f"<a href=\"{link}\">Открыть пост</a>\n\n"
        "Это ещё не значит, что рилс недоступен. Выбери формат — бот попробует скачать напрямую."
    )




def _is_image_file(path: str) -> bool:
    return str(path or "").lower().endswith((".jpg", ".jpeg", ".png", ".webp"))


def _threads_text_fallback(info: dict | None, url: str) -> str:
    """Render a Threads text-only post when there is no media file."""
    link = html.escape(url or "", quote=True)
    title = html.escape(str((info or {}).get("title") or "Threads post")[:500])
    desc = html.escape(str((info or {}).get("description") or "")[:3000])
    uploader = html.escape(str((info or {}).get("uploader") or ""))
    parts = ["🧵 <b>Threads</b>"]
    if uploader:
        parts.append(f"👤 {uploader}")
    if desc and desc != title:
        parts.append(f"<blockquote>{desc}</blockquote>")
    elif title:
        parts.append(f"<blockquote>{title}</blockquote>")
    parts.append(f'<a href="{link}">Открыть пост</a>')
    return "\n".join(parts)


async def _refresh_instagram_cookies_best_effort() -> bool:
    """Try to refresh Instagram cookies if the project has services.cookies."""
    try:
        from services.cookies import refresh_cookies
    except Exception:
        return False
    try:
        return bool(await refresh_cookies())
    except Exception:
        return False


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    else:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


# ─── Download progress indicator ────────────────────────────
def _progress_bar(percent: int, width: int = 12) -> str:
    """Return a compact Telegram-friendly progress bar."""
    percent = max(0, min(100, int(percent)))
    filled = round(width * percent / 100)
    return "█" * filled + "░" * (width - filled)


def _progress_text(lang: str, percent: int, stage: str = "download") -> str:
    """Visual progress text shown while yt-dlp is running.

    This is an indeterminate progress indicator: without a downloader callback
    we cannot know the exact byte percentage, so it advances up to 95% while the
    task is alive, then switches to upload when the download finishes.
    """
    labels = {
        "ru": {
            "download": "📥 <b>Скачиваю...</b>",
            "upload": "📤 <b>Загружаю в Telegram...</b>",
            "wait": "⏳ Это может занять время",
        },
        "uk": {
            "download": "📥 <b>Завантажую...</b>",
            "upload": "📤 <b>Відправляю в Telegram...</b>",
            "wait": "⏳ Це може зайняти час",
        },
        "en": {
            "download": "📥 <b>Downloading...</b>",
            "upload": "📤 <b>Uploading to Telegram...</b>",
            "wait": "⏳ This may take a while",
        },
    }
    tr = labels.get(lang, labels["en"])
    return f"{tr.get(stage, tr['download'])}\n<code>{_progress_bar(percent)}</code> {percent}%\n{tr['wait']}"


async def _animate_download_progress(status_msg, lang: str, stop_event: asyncio.Event):
    """Edit the status message every few seconds while the download is active.

    Telegram rate-limits frequent edits, so keep updates slow and ignore edit
    errors (for example, if text did not change or the message was deleted).
    """
    percent = 3
    # Slows down over time and caps at 95% until the real task completes.
    increments = [7, 8, 6, 7, 5, 6, 4, 5, 4, 3, 3, 2, 2, 2, 1]
    idx = 0
    while not stop_event.is_set():
        try:
            await status_msg.edit_text(_progress_text(lang, percent), parse_mode="HTML")
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=2.0)
            break
        except asyncio.TimeoutError:
            pass
        if percent < 95:
            inc = increments[idx] if idx < len(increments) else 1
            idx += 1
            percent = min(95, percent + inc)


@router.message(F.text.regexp(r"^@[\w.]{1,30}$"))
async def handle_username(message: Message, bot: Bot):
    """Handle @username - fetch all Instagram stories."""
    user_id = message.from_user.id
    lang = await _effective_message_language(message, user_id)
    username = message.text.strip().lstrip("@")

    if await get_setting("feature_bulk_stories", "1") != "1" or await get_setting("feature_instagram", "1") != "1":
        await message.answer(t(lang, "feature_disabled"))
        return

    ok, err = await can_download(user_id)
    if not ok:
        await message.answer(err)
        return

    url = f"https://www.instagram.com/stories/{username}/"
    await handle_bulk_stories(message, bot, url, user_id)


async def handle_bulk_stories(message: Message, bot: Bot, url: str, user_id: int, lang: str = None):
    """Handle bulk story download for instagram.com/stories/username/"""
    lang = lang or await _effective_message_language(message, user_id)
    loading = await message.answer(t(lang, "fetching_stories"))

    stories = await get_stories_list(url)
    if not stories:
        await loading.edit_text(t(lang, "no_stories"))
        return

    total = len(stories)
    await loading.edit_text(t(lang, "stories_found", total=total))

    downloaded = 0
    failed = 0

    for story in stories:
        i = story.index
        ok, err = await can_download(user_id)
        if not ok:
            await message.answer(err)
            break

        if is_downloading(user_id) and cancel_download(user_id):
            await message.answer(t(lang, "cancelled"))
            return

        progress_msg = await message.answer(t(lang, "story_progress", i=i, total=total))

        from services.bulk_stories import download_story_by_index
        result = await download_story_by_index(url, i)

        if not result["success"]:
            failed += 1
            err_msg = result["error"][:50] if result["error"] else ""
            await progress_msg.edit_text(t(lang, "dl_failed", error=err_msg))
            continue

        file_path = result["file_path"]
        file_size = result["file_size"]

        if file_size > config.MAX_FILE_SIZE:
            cleanup_file(file_path)
            failed += 1
            await progress_msg.edit_text(t(lang, "too_large", size=format_size(file_size)))
            continue

        try:
            caption = t(lang, "story_progress", i=i, total=total)
            file = FSInputFile(file_path)
            await bot.send_video(
                chat_id=user_id, video=file, caption=caption,
                parse_mode="HTML", supports_streaming=True,
            )
            downloaded += 1
            await record_download(user_id, url, "instagram", result["title"], file_size, chat_id=message.chat.id)
            await progress_msg.delete()
        except Exception as e:
            failed += 1
            await progress_msg.edit_text(t(lang, "upload_failed", error=str(e)[:50]))
        finally:
            cleanup_file(file_path)

    await message.answer(t(lang, "stories_summary", ok=downloaded, total=total))


@router.message(F.text.regexp(r"https?://\S+"))
async def handle_link(message: Message, bot: Bot):
    user_id = message.from_user.id
    url = _normalize_threads_url(message.text)

    is_group = message.chat.type in ("group", "supergroup", "channel")
    group_settings = None
    if is_group:
        group_settings = await get_group_settings(message.chat.id)
        if group_settings is None:
            # Register old/lazy chats and default their language to the sender's language.
            await ensure_group_chat(
                message.chat.id, message.chat.title, message.chat.type,
                language=await get_user_language(user_id),
            )
            group_settings = await get_group_settings(message.chat.id)
    lang = (group_settings.get("language") if group_settings else None) or await get_user_language(user_id)

    if is_downloading(user_id):
        await message.reply(t(lang, "already_downloading"))
        return

    ok, err = await can_download(user_id)
    if not ok:
        await message.reply(err)
        return

    result = detect_platform(url)
    if not result:
        await message.reply(t(lang, "unrecognized_link"))
        return

    platform, video_id = result
    pinfo = get_platform_info(platform)

    if not await _platform_enabled(platform):
        await message.reply(t(lang, "feature_disabled"))
        return

    if platform == "instagram" and "stories/" in url and not video_id.isdigit():
        await handle_bulk_stories(message, bot, url, user_id, lang=lang)
        return

    # Decide whether to auto-download or show the quality/format buttons.
    #   • In groups/channels: the admin's group_download_mode applies.
    #   • In private chats: the user's personal download_mode applies
    #     (set in their ⚙️ Settings menu). Default "ask" shows buttons.
    if is_group:
        # Per-group download mode (set by the group's admin in "My groups").
        g = group_settings
        auto_mode = g["download_mode"] if g else await get_setting("group_download_mode", "ask")
    else:
        auto_mode = await get_user_download_mode(user_id)

    if auto_mode in ("video", "audio"):
        # Free auto-video mode should use the same free quality as the
        # "📱 480p (Free)" button, not unrestricted best quality. Premium
        # qualities still go through Stars via handlers/stars.py.
        quality = "audio" if auto_mode == "audio" else "480"
        loading = await message.reply(t(lang, "analyzing"))
        short_id = store_url(url, platform)
        await process_quality_download(
            bot, user_id, quality, short_id, message.chat.id, loading,
            via_user=_message_via_user(message), via_chat=_message_via_chat(message), reply_to_message_id=message.message_id,
        )
        return

    loading = await message.reply(t(lang, "analyzing"))

    # TikTok: skip the get_info gate (often fails even when download works)
    if platform == "tiktok":
        await loading.edit_text(
            t(lang, "tiktok_choose"),
            parse_mode="HTML",
            reply_markup=quality_keyboard(store_url(url, platform), platform),
        )
        return

    info = await get_info(url, platform)
    if not info:
        if platform == "instagram":
            # Instagram often blocks metadata/preview requests even when direct
            # media download still succeeds. Do not stop here with "no access";
            # show quality buttons and let process_quality_download try directly.
            await loading.edit_text(
                _instagram_preview_fallback_text(lang, url),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=quality_keyboard(store_url(url, platform), platform),
            )
        elif platform == "threads":
            # Threads metadata can fail while direct yt-dlp download may still
            # work. Let the user try a direct download instead of stopping.
            await loading.edit_text(
                "🧵 <b>Threads не отдал предпросмотр.</b>\n\nПопробуй скачать напрямую.",
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=quality_keyboard(store_url(url, platform), platform),
            )
        else:
            await loading.edit_text(t(lang, "cant_fetch"))
        return

    title = info.get("title", "Unknown")[:80]
    title_safe = html.escape(title)
    duration = info.get("duration")
    uploader = info.get("uploader", "")

    text = f"{pinfo.icon} <b>{title_safe}</b>"
    if uploader:
        text += f"\n\U0001F464 {html.escape(uploader)}"
    if duration:
        text += f"\n\u23F1 {format_duration(duration)}"
    if pinfo.note:
        text += f"\n\U0001F4A1 {pinfo.note}"

    await loading.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=quality_keyboard(store_url(url, platform), platform),
    )


@router.callback_query(F.data.startswith("dl:"))
async def process_download(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer("Invalid request")
        return
    quality = parts[1]
    short_id = parts[2]
    await callback.answer()
    # Reply the result to the original link message. The buttons message
    # (callback.message) was sent as a reply to that link, so its
    # reply_to_message points back to it.
    orig = callback.message.reply_to_message
    reply_to_id = orig.message_id if orig else None
    await process_quality_download(
        bot, user_id, quality, short_id, callback.message.chat.id, callback.message,
        via_user=_message_via_user(orig) or callback.from_user,
        via_chat=_message_via_chat(orig),
        reply_to_message_id=reply_to_id,
    )


async def process_quality_download(bot: Bot, user_id: int, quality: str, short_id: str, chat_id: int, edit_msg=None, via_user=None, via_chat=None, reply_to_message_id=None):
    """Download logic shared between regular and premium (Stars-paid) downloads."""
    lang = await _effective_chat_language(chat_id, user_id)
    audio_only = quality == "audio"

    url_data = get_url(short_id)
    if not url_data:
        msg = t(lang, "link_expired")
        if edit_msg:
            await edit_msg.edit_text(msg)
        else:
            await bot.send_message(chat_id, msg)
        return
    url, platform = url_data
    url = _normalize_threads_url(url)

    # Personal preferences only apply in private chats (chat_id > 0). In groups
    # the per-group settings drive caption behaviour instead.
    user_prefs = await get_user_settings(user_id) if chat_id > 0 else None
    watermark = bool(user_prefs and user_prefs.get("tiktok_watermark"))

    if quality not in ("audio", "720", "1080", "4k"):
        ok, err = await can_download(user_id)
        if not ok:
            if edit_msg:
                await edit_msg.edit_text(err)
            else:
                await bot.send_message(chat_id, err)
            return

    if edit_msg:
        status_msg = await edit_msg.edit_text(_progress_text(lang, 3), parse_mode="HTML")
    else:
        status_msg = await bot.send_message(chat_id, _progress_text(lang, 3), parse_mode="HTML")

    # Photo carousel / slideshow delivery prefs (private chats only; groups get
    # the default album + no separate audio).
    gallery_mode = user_prefs.get("gallery_mode", "photos") if user_prefs else "photos"
    audio_mode = user_prefs.get("audio_mode", "off") if user_prefs else "off"

    async def _run_gallery(gal):
        """Send a gallery result and return True if handled."""
        try:
            return await process_gallery(
                bot, user_id, url, platform, gal, chat_id, status_msg,
                via_user=via_user, via_chat=via_chat, reply_to_message_id=reply_to_message_id,
                gallery_mode=gallery_mode, audio_mode=audio_mode,
            )
        finally:
            cleanup_gallery(gal)

    # Instagram carousels need every item, so detect a photo post up front
    # (get_info is reliable for IG with cookies). TikTok detection is handled by
    # the post-failure fallback below (slideshow video downloads fail cleanly).
    if not audio_only and platform == "instagram":
        info = await get_info(url, platform)
        if is_photo_post(info):
            gal = await download_gallery(url, platform)
            if gal and gal.success:
                await _run_gallery(gal)
                return
            cleanup_gallery(gal)

    async def do_download():
        return await _download_compat(url, platform, audio_only=audio_only, quality=quality, watermark=watermark)

    task = asyncio.create_task(do_download())
    progress_stop = asyncio.Event()
    progress_task = asyncio.create_task(_animate_download_progress(status_msg, lang, progress_stop))
    set_active(user_id, task)

    try:
        result = await task
    except asyncio.CancelledError:
        progress_stop.set()
        progress_task.cancel()
        await status_msg.edit_text(t(lang, "cancelled"))
        return
    finally:
        progress_stop.set()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass
        clear_active(user_id)

    if not result.success:
        # Instagram sometimes returns "empty media response" when cookies are
        # missing/expired. Try refreshing cookies once, then retry the download.
        if platform == "instagram" and _is_instagram_access_error(result.error):
            await status_msg.edit_text("🔄 <b>Обновляю Instagram cookies...</b>", parse_mode="HTML")
            if await _refresh_instagram_cookies_best_effort():
                retry = await _download_compat(url, platform, audio_only=audio_only, quality=quality, watermark=watermark)
                if retry.success:
                    result = retry
                else:
                    result = retry

        if not result.success:
            # Fallback: a photo carousel / TikTok slideshow has no playable video,
            # so the normal download fails — try a gallery download instead.
            if not audio_only and platform in ("tiktok", "instagram"):
                gal = await download_gallery(url, platform)
                if gal and gal.success:
                    await _run_gallery(gal)
                    return
                cleanup_gallery(gal)

            if platform == "instagram" and _is_instagram_access_error(result.error):
                await status_msg.edit_text(
                    _instagram_access_message(lang, url, result.error),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                return

            if platform == "threads":
                # Threads may be a text-only post or yt-dlp may expose only
                # metadata. In that case, forward the message text/link instead
                # of failing with a generic download error.
                try:
                    info = await get_info(url, platform)
                except Exception:
                    info = None
                if info:
                    await status_msg.edit_text(
                        _threads_text_fallback(info, url),
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    await record_download(user_id, url, platform, (info or {}).get("title") or "Threads post", 0, chat_id=chat_id)
                    return

            error_text = result.error[:150] if result.error else "Unknown error"
            await status_msg.edit_text(t(lang, "dl_failed", error=error_text), parse_mode="HTML")
            return

    # Effective caption flags + per-group "delete user's link" behaviour.
    cfg = await _resolve_caption_config(chat_id, user_id, user_prefs)
    show_tags = cfg["show_tags"]
    show_source_channel = cfg["show_source_channel"]
    delete_user_url = cfg["delete_user_url"]
    caption_mode = cfg["caption_mode"]
    desc_mode = cfg["desc_mode"]

    async def _maybe_delete_user_link():
        if delete_user_url and reply_to_message_id:
            try:
                await bot.delete_message(chat_id, reply_to_message_id)
            except Exception:
                pass  # bot may lack delete rights, or message already gone

    async def _maybe_send_description():
        """Send the post description as its own message (desc_mode='separate')."""
        if desc_mode != "separate":
            return
        text = _clean_source_description(result.description or "")
        if not text:
            return
        try:
            await bot.send_message(
                chat_id,
                "<blockquote>" + html.escape(text[:3500]) + "</blockquote>",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            pass

    if result.file_size > config.MAX_FILE_SIZE:
        await status_msg.edit_text(t(lang, "too_large_split", size=format_size(result.file_size)), parse_mode="HTML")
        from services.downloader import split_video
        try:
            parts = await asyncio.get_event_loop().run_in_executor(None, split_video, result.file_path)
        except Exception as e:
            cleanup_file(result.file_path)
            await status_msg.edit_text(t(lang, "split_failed", error=str(e)[:100]), parse_mode="HTML")
            return

        if len(parts) <= 1:
            cleanup_file(result.file_path)
            await status_msg.edit_text(t(lang, "too_large", size=format_size(result.file_size)), parse_mode="HTML")
            return

        await status_msg.edit_text(t(lang, "uploading_parts", count=len(parts)), parse_mode="HTML")
        for i, part_path in enumerate(parts, 1):
            try:
                part_size = os.path.getsize(part_path)
                caption = f"\U0001F3AC <b>{html.escape(result.title or '')}</b>\n\U0001F4E6 {i}/{len(parts)} \u2014 {format_size(part_size)}"
                file = FSInputFile(part_path)
                await bot.send_video(
                    chat_id=chat_id, video=file, caption=caption,
                    parse_mode="HTML", supports_streaming=True,
                    reply_to_message_id=reply_to_message_id if i == 1 else None,
                )
                cleanup_file(part_path)
            except Exception as e:
                await bot.send_message(chat_id, t(lang, "part_failed", i=i, error=str(e)[:50]))
                cleanup_file(part_path)

        await _maybe_send_description()
        await record_download(user_id, url, platform, result.title, result.file_size, chat_id=chat_id)
        await _maybe_delete_user_link()
        await status_msg.delete()
        cleanup_file(result.file_path)
        return

    await status_msg.edit_text(_progress_text(lang, 100, "upload"), parse_mode="HTML")

    try:
        caption = build_caption(
            result, via_user=via_user, via_chat=via_chat,
            show_tags=show_tags, show_source_channel=show_source_channel,
            caption_mode=caption_mode, desc_mode=desc_mode,
        )

        file = FSInputFile(result.file_path)
        if audio_only:
            await bot.send_audio(
                chat_id=chat_id, audio=file, caption=caption, parse_mode="HTML",
                reply_to_message_id=reply_to_message_id,
            )
        elif _is_image_file(result.file_path):
            await bot.send_photo(
                chat_id=chat_id, photo=file, caption=caption,
                parse_mode="HTML", reply_to_message_id=reply_to_message_id,
            )
        else:
            await bot.send_video(
                chat_id=chat_id, video=file, caption=caption,
                parse_mode="HTML", supports_streaming=True,
                reply_to_message_id=reply_to_message_id,
            )

        await _maybe_send_description()
        await record_download(user_id, url, platform, result.title, result.file_size, chat_id=chat_id)
        await _maybe_delete_user_link()
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(t(lang, "upload_failed", error=str(e)[:100]))
    finally:
        cleanup_file(result.file_path)


async def _resolve_caption_config(chat_id: int, user_id: int, user_prefs=None) -> dict:
    """Resolve effective caption/description flags for a chat.

    • Groups/channels (chat_id < 0): per-group settings configured in
      "My groups". Admin global flags act as a force-on-for-everyone OR.
    • Private chats (chat_id > 0): the user's personal ⚙️ Settings.
    """
    admin_tags = await get_setting("feature_show_tags", "0") == "1"
    admin_channel = await get_setting("feature_show_source_channel", "0") == "1"
    cfg = {
        "show_tags": admin_tags,
        "show_source_channel": admin_channel,
        "delete_user_url": False,
        "caption_mode": "src_via",   # default credit line (groups keep this)
        "desc_mode": "off",          # default: no description (groups keep this)
    }
    if chat_id < 0:
        g = await get_group_settings(chat_id)
        if g:
            cfg["show_tags"] = admin_tags or g["show_tags"]
            cfg["show_source_channel"] = admin_channel or g["show_source_channel"]
            cfg["delete_user_url"] = g["delete_user_url"]
            cfg["caption_mode"] = g.get("caption_mode", "src_via")
            cfg["desc_mode"] = g.get("description_mode", "off")
    else:
        if user_prefs is None:
            user_prefs = await get_user_settings(user_id)
        cfg["show_tags"] = admin_tags or user_prefs["show_tags"]
        cfg["show_source_channel"] = admin_channel or user_prefs["show_source_channel"]
        cfg["caption_mode"] = user_prefs.get("caption_mode", "src_via")
        cfg["desc_mode"] = user_prefs.get("description_mode", "off")
    return cfg


async def process_gallery(bot: Bot, user_id: int, url: str, platform: str,
                          gallery: GalleryResult, chat_id: int, status_msg,
                          via_user=None, via_chat=None, reply_to_message_id=None,
                          gallery_mode: str = "photos", audio_mode: str = "off"):
    """Send a downloaded photo carousel / slideshow post.

    gallery_mode='photos' → send the images as an album (+ any carousel videos).
    gallery_mode='video'  → render the images into a slideshow video with the
                            post's music.
    audio_mode='separate' → also send the post's audio as a standalone .mp3.
    """
    lang = await _effective_chat_language(chat_id, user_id)
    cfg = await _resolve_caption_config(chat_id, user_id)

    caption = build_caption(
        gallery, via_user=via_user, via_chat=via_chat,
        show_tags=cfg["show_tags"], show_source_channel=cfg["show_source_channel"],
        caption_mode=cfg["caption_mode"], desc_mode=cfg["desc_mode"],
    )

    images = [p for p in gallery.image_paths if os.path.exists(p) and os.path.getsize(p) <= config.MAX_FILE_SIZE]
    videos = [p for p in gallery.video_paths if os.path.exists(p) and os.path.getsize(p) <= config.MAX_FILE_SIZE]
    sent_any = False
    slideshow_path = None

    try:
        await status_msg.edit_text(_progress_text(lang, 100, "upload"), parse_mode="HTML")
    except Exception:
        pass

    async def _send_caption_only():
        # Album caption goes on the first media item; if we couldn't, post it separately.
        if caption:
            try:
                await bot.send_message(chat_id, caption, parse_mode="HTML",
                                       disable_web_page_preview=True,
                                       reply_to_message_id=reply_to_message_id)
            except Exception:
                pass

    # ── VIDEO (slideshow) mode ──
    if gallery_mode == "video" and images:
        try:
            slideshow_path = await asyncio.get_event_loop().run_in_executor(
                None, build_slideshow, images, gallery.audio_path
            )
        except Exception:
            slideshow_path = None
        if slideshow_path and os.path.exists(slideshow_path) and os.path.getsize(slideshow_path) <= config.MAX_FILE_SIZE:
            try:
                await bot.send_video(
                    chat_id=chat_id, video=FSInputFile(slideshow_path), caption=caption,
                    parse_mode="HTML", supports_streaming=True,
                    reply_to_message_id=reply_to_message_id,
                )
                sent_any = True
            except Exception:
                slideshow_path = None
        # Fall through to album mode if the slideshow couldn't be built/sent.

    # ── PHOTO album mode (default, or slideshow fallback) ──
    if not sent_any and images:
        first_caption_used = False
        # Telegram media groups are capped at 10 items.
        for chunk_start in range(0, len(images), 10):
            chunk = images[chunk_start:chunk_start + 10]
            media = []
            for idx, img in enumerate(chunk):
                cap = None
                pm = None
                if not first_caption_used and idx == 0 and caption:
                    cap = caption
                    pm = "HTML"
                    first_caption_used = True
                media.append(InputMediaPhoto(media=FSInputFile(img), caption=cap, parse_mode=pm))
            try:
                await bot.send_media_group(
                    chat_id=chat_id, media=media,
                    reply_to_message_id=reply_to_message_id if chunk_start == 0 else None,
                )
                sent_any = True
            except Exception:
                # Fall back to sending each image as a document.
                for img in chunk:
                    try:
                        await bot.send_document(chat_id=chat_id, document=FSInputFile(img))
                        sent_any = True
                    except Exception:
                        pass
        if sent_any and not first_caption_used:
            await _send_caption_only()

    # ── Any standalone videos in the carousel ──
    for vid in videos:
        try:
            await bot.send_video(chat_id=chat_id, video=FSInputFile(vid),
                                 supports_streaming=True)
            sent_any = True
        except Exception:
            pass

    # ── Separate audio (TikTok photo+audio "everything separately") ──
    if audio_mode == "separate" and gallery.audio_path and os.path.exists(gallery.audio_path):
        if os.path.getsize(gallery.audio_path) <= config.MAX_FILE_SIZE:
            try:
                title = gallery.title or "audio"
                await bot.send_audio(chat_id=chat_id, audio=FSInputFile(gallery.audio_path),
                                     title=title[:64])
                sent_any = True
            except Exception:
                pass

    # ── Separate description message (desc_mode='separate') ──
    if cfg["desc_mode"] == "separate":
        text = (gallery.description or "").strip()
        if text:
            try:
                await bot.send_message(
                    chat_id, "<blockquote>" + html.escape(text[:3500]) + "</blockquote>",
                    parse_mode="HTML", disable_web_page_preview=True,
                )
            except Exception:
                pass

    if not sent_any:
        try:
            await status_msg.edit_text(t(lang, "dl_failed", error="gallery upload failed"), parse_mode="HTML")
        except Exception:
            pass
        return False

    await record_download(user_id, url, platform, gallery.title, 0, chat_id=chat_id)
    if cfg["delete_user_url"] and reply_to_message_id:
        try:
            await bot.delete_message(chat_id, reply_to_message_id)
        except Exception:
            pass
    try:
        await status_msg.delete()
    except Exception:
        pass
    return True


@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    lang = await get_user_language(message.from_user.id)
    if cancel_download(message.from_user.id):
        await message.answer(t(lang, "cancelled"))
    else:
        await message.answer(t(lang, "no_active"))


@router.callback_query(F.data == "cancel")
async def cancel_button(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    if cancel_download(callback.from_user.id):
        await callback.message.edit_text(t(lang, "cancelled"))
    await callback.answer()
