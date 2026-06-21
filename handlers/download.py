import asyncio
import os
import html
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from database.db import (
    can_download, record_download, use_extra_download,
    get_setting, get_user_language, get_user_download_mode, get_user_settings,
    get_group_settings, ensure_group_chat,
)
from services.platform import detect_platform, get_platform_info
from services.downloader import (
    download, get_info, cleanup_file, DownloadResult,
    download_gallery, build_slideshow, cleanup_gallery, is_photo_post, GalleryResult,
)
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


def _platform_label(platform: str) -> str:
    return {
        "youtube": "YouTube",
        "instagram": "Instagram",
        "tiktok": "TikTok",
    }.get(platform, "Джерело")


def _author_url(result) -> str:
    """Best-effort link to the content author's profile."""
    login = (result.uploader_id or "").lstrip("@")
    platform = result.platform
    if login:
        if platform == "tiktok":
            return f"https://www.tiktok.com/@{login}"
        if platform == "instagram":
            return f"https://instagram.com/{login}"
    # Fallback: the post link itself.
    return result.source_url or ""


def build_caption(result, via_user=None, show_tags=False, show_source_channel=False,
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

    # "Via" points to the user who sent the link.
    via_url = None
    via_text = "Via"
    if via_user is not None:
        uname = getattr(via_user, "username", None)
        uid = getattr(via_user, "id", None)
        if uname:
            via_url = f"https://t.me/{uname}"
        elif uid:
            via_url = f"tg://user?id={uid}"
    if not via_url:
        via_url = f"https://t.me/{BOT_USERNAME}?start={VIA_START_PARAM}"

    src_link = f"🎬 <a href=\"{html.escape(source_url, quote=True)}\">Джерело</a>"
    via_link = f"<a href=\"{html.escape(via_url, quote=True)}\">{html.escape(via_text)}</a>"

    login = (result.uploader_id or "").lstrip("@")
    author_url = _author_url(result)
    if login and author_url:
        author_link = f"👤 <a href=\"{html.escape(author_url, quote=True)}\">@{html.escape(login)}</a>"
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
        quote_lines.append(f"@{html.escape(login)}")
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
        desc = (result.description or "").strip()
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
    }.get(platform)
    if not key:
        return True
    return await get_setting(key, "1") == "1"


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


@router.message(F.text.regexp(r"^@[\w.]{1,30}$"))
async def handle_username(message: Message, bot: Bot):
    """Handle @username - fetch all Instagram stories."""
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
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


async def handle_bulk_stories(message: Message, bot: Bot, url: str, user_id: int):
    """Handle bulk story download for instagram.com/stories/username/"""
    lang = await get_user_language(user_id)
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
    lang = await get_user_language(user_id)
    url = message.text.strip()

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
        await handle_bulk_stories(message, bot, url, user_id)
        return

    # Decide whether to auto-download or show the quality/format buttons.
    #   • In groups/channels: the admin's group_download_mode applies.
    #   • In private chats: the user's personal download_mode applies
    #     (set in their ⚙️ Settings menu). Default "ask" shows buttons.
    is_group = message.chat.type in ("group", "supergroup", "channel")
    if is_group:
        # Per-group download mode (set by the group's admin in "My groups").
        g = await get_group_settings(message.chat.id)
        if g is None:
            # Chat existed before this feature — register it now so it shows up
            # for whoever opens the group list later. added_by stays unknown.
            await ensure_group_chat(message.chat.id, message.chat.title, message.chat.type)
            g = await get_group_settings(message.chat.id)
        auto_mode = g["download_mode"] if g else await get_setting("group_download_mode", "ask")
    else:
        auto_mode = await get_user_download_mode(user_id)

    if auto_mode in ("video", "audio"):
        quality = "audio" if auto_mode == "audio" else "best"
        loading = await message.reply(t(lang, "analyzing"))
        short_id = store_url(url, platform)
        await process_quality_download(
            bot, user_id, quality, short_id, message.chat.id, loading,
            via_user=message.from_user, reply_to_message_id=message.message_id,
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
            await loading.edit_text(t(lang, "ig_cant_access"), parse_mode="HTML")
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
        via_user=callback.from_user, reply_to_message_id=reply_to_id,
    )


async def process_quality_download(bot: Bot, user_id: int, quality: str, short_id: str, chat_id: int, edit_msg=None, via_user=None, reply_to_message_id=None):
    """Download logic shared between regular and premium (Stars-paid) downloads."""
    lang = await get_user_language(user_id)
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
        status_msg = await edit_msg.edit_text(t(lang, "downloading"), parse_mode="HTML")
    else:
        status_msg = await bot.send_message(chat_id, t(lang, "downloading"), parse_mode="HTML")

    # Photo carousel / slideshow delivery prefs (private chats only; groups get
    # the default album + no separate audio).
    gallery_mode = user_prefs.get("gallery_mode", "photos") if user_prefs else "photos"
    audio_mode = user_prefs.get("audio_mode", "off") if user_prefs else "off"

    async def _run_gallery(gal):
        """Send a gallery result and return True if handled."""
        try:
            return await process_gallery(
                bot, user_id, url, platform, gal, chat_id, status_msg,
                via_user=via_user, reply_to_message_id=reply_to_message_id,
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
        return await download(url, platform, audio_only=audio_only, quality=quality, watermark=watermark)

    task = asyncio.create_task(do_download())
    set_active(user_id, task)

    try:
        result = await task
    except asyncio.CancelledError:
        await status_msg.edit_text(t(lang, "cancelled"))
        return
    finally:
        clear_active(user_id)

    if not result.success:
        # Fallback: a photo carousel / TikTok slideshow has no playable video,
        # so the normal download fails — try a gallery download instead.
        if not audio_only and platform in ("tiktok", "instagram"):
            gal = await download_gallery(url, platform)
            if gal and gal.success:
                await _run_gallery(gal)
                return
            cleanup_gallery(gal)
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
        text = (result.description or "").strip()
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

    await status_msg.edit_text(t(lang, "uploading"), parse_mode="HTML")

    try:
        caption = build_caption(
            result, via_user=via_user,
            show_tags=show_tags, show_source_channel=show_source_channel,
            caption_mode=caption_mode, desc_mode=desc_mode,
        )

        file = FSInputFile(result.file_path)
        if audio_only:
            await bot.send_audio(
                chat_id=chat_id, audio=file, caption=caption, parse_mode="HTML",
                reply_to_message_id=reply_to_message_id,
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
                          via_user=None, reply_to_message_id=None,
                          gallery_mode: str = "photos", audio_mode: str = "off"):
    """Send a downloaded photo carousel / slideshow post.

    gallery_mode='photos' → send the images as an album (+ any carousel videos).
    gallery_mode='video'  → render the images into a slideshow video with the
                            post's music.
    audio_mode='separate' → also send the post's audio as a standalone .mp3.
    """
    lang = await get_user_language(user_id)
    cfg = await _resolve_caption_config(chat_id, user_id)

    caption = build_caption(
        gallery, via_user=via_user,
        show_tags=cfg["show_tags"], show_source_channel=cfg["show_source_channel"],
        caption_mode=cfg["caption_mode"], desc_mode=cfg["desc_mode"],
    )

    images = [p for p in gallery.image_paths if os.path.exists(p) and os.path.getsize(p) <= config.MAX_FILE_SIZE]
    videos = [p for p in gallery.video_paths if os.path.exists(p) and os.path.getsize(p) <= config.MAX_FILE_SIZE]
    sent_any = False
    slideshow_path = None

    try:
        await status_msg.edit_text(t(lang, "uploading"), parse_mode="HTML")
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
