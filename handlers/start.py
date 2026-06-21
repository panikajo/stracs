from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from database.db import (
    get_or_create_user, get_user_language, set_user_language, get_setting,
    get_chat_download_stats,
)
from services.i18n import t, LANGUAGES
from services.platform import get_platform_info
from keyboards.inline import main_menu_keyboard, language_keyboard
from config import config

router = Router()


async def _menu_flags():
    """Read admin toggles that affect the user menu."""
    show_buy = await get_setting("feature_stars", "1") == "1"
    show_lang = await get_setting("feature_language_select", "1") == "1"
    show_settings = await get_setting("feature_user_settings", "1") == "1"
    return show_buy, show_lang, show_settings


async def send_main_menu(message: Message, lang: str):
    # In groups/channels: don't attach the reply keyboard unless the admin
    # explicitly enabled it (feature_group_buttons, default OFF). Instead show
    # a short capabilities intro.
    is_private = message.chat.type == "private"
    if not is_private:
        group_buttons_on = await get_setting("feature_group_buttons", "0") == "1"
        if not group_buttons_on:
            await message.answer(t(lang, "group_intro"), parse_mode="HTML")
            return

    show_buy, show_lang, show_settings = await _menu_flags()
    is_admin = is_private and message.chat.id == config.ADMIN_ID
    await message.answer(
        t(lang, "welcome"),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(
            lang, show_buy=show_buy, show_language=show_lang,
            is_admin=is_admin, show_settings=show_settings,
        ),
    )


@router.message(CommandStart())
async def cmd_start(message: Message):
    await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    lang = await get_user_language(message.from_user.id)
    await send_main_menu(message, lang)


async def _buttons_allowed(message: Message) -> bool:
    """Reply-keyboard buttons work in private always; in groups only if enabled."""
    if message.chat.type == "private":
        return True
    return await get_setting("feature_group_buttons", "0") == "1"


# ─── Button: Help ───────────────────────────────────────────
@router.message(F.text.func(lambda txt: txt and any(
    txt == t(code, "btn_help") for code in LANGUAGES
)))
async def btn_help(message: Message):
    if not await _buttons_allowed(message):
        return
    lang = await get_user_language(message.from_user.id)
    await message.answer(t(lang, "help"), parse_mode="HTML")


# Order platforms are listed in the chat-stats message.
_PLATFORM_ORDER = ["youtube", "instagram", "tiktok"]


def _platform_lines(counts: dict) -> str:
    """Render '🔴 YouTube — 12' lines for a {platform: count} dict."""
    keys = [p for p in _PLATFORM_ORDER if p in counts]
    keys += [p for p in counts if p not in _PLATFORM_ORDER]  # any extras (e.g. unknown)
    lines = []
    for p in keys:
        info = get_platform_info(p)
        lines.append(f"{info.icon} {info.name} \u2014 {counts[p]}")
    return "\n".join(lines)


async def _render_chat_stats(message: Message, lang: str):
    """Per-chat download stats grouped by platform (used in groups/channels)."""
    s = await get_chat_download_stats(message.chat.id)
    if s["all_total"] == 0:
        await message.answer(t(lang, "chat_stats_none"), parse_mode="HTML")
        return
    parts = [t(lang, "chat_stats_title")]
    # Today
    parts.append("")
    parts.append(t(lang, "chat_stats_today"))
    if s["today_total"] == 0:
        parts.append(t(lang, "chat_stats_zero"))
    else:
        parts.append(_platform_lines(s["today"]))
        parts.append(t(lang, "chat_stats_total_line", n=s["today_total"]))
    # All-time
    parts.append("")
    parts.append(t(lang, "chat_stats_alltime"))
    parts.append(_platform_lines(s["total"]))
    parts.append(t(lang, "chat_stats_total_line", n=s["all_total"]))
    await message.answer("\n".join(parts), parse_mode="HTML")


# ─── My stats (button + /stats command) ─────────────────────
async def _render_stats(message: Message):
    lang = await get_user_language(message.from_user.id)
    # In groups/channels /stats shows this chat's download counts by platform.
    if message.chat.type != "private":
        await _render_chat_stats(message, lang)
        return
    # Private chat: personal usage/limits (unchanged).
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    limit = user["daily_limit"] if user["daily_limit"] is not None else config.DAILY_LIMIT
    used = user["downloads_today"]
    extra = user["extra_downloads"]
    remaining = "\u221E" if limit == 0 else str(limit - used + extra)
    limit_disp = "\u221E" if limit == 0 else str(limit)
    await message.answer(
        t(lang, "stats", used=used, limit=limit_disp, extra=extra, remaining=remaining),
        parse_mode="HTML",
    )


@router.message(F.text.func(lambda txt: txt and any(
    txt == t(code, "btn_stats") for code in LANGUAGES
)))
async def btn_stats(message: Message):
    if not await _buttons_allowed(message):
        return
    await _render_stats(message)


# /stats works everywhere (private chats and groups, for any member)
@router.message(Command("stats"))
async def cmd_stats(message: Message):
    await _render_stats(message)


async def _is_group_admin(bot, chat_id: int, user_id: int) -> bool:
    """True if user_id is an administrator or the creator of the group/chat."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def _open_language(message: Message):
    """Show the language picker (after feature + permission checks)."""
    lang = await get_user_language(message.from_user.id)
    if await get_setting("feature_language_select", "1") != "1":
        await message.answer(t(lang, "feature_disabled"))
        return
    await message.answer(t(lang, "choose_language"), reply_markup=language_keyboard())


# ─── Button: Language ───────────────────────────────────────
@router.message(F.text.func(lambda txt: txt and any(
    txt == t(code, "btn_language") for code in LANGUAGES
)))
async def btn_language(message: Message):
    if not await _buttons_allowed(message):
        return
    await _open_language(message)


@router.callback_query(F.data.startswith("lang:"))
async def set_language_cb(callback: CallbackQuery):
    code = callback.data.split(":", 1)[1]
    if code not in LANGUAGES:
        await callback.answer()
        return
    # In groups only admins may change the language (matches /language gating).
    chat = callback.message.chat
    if chat.type != "private" and not await _is_group_admin(
        callback.bot, chat.id, callback.from_user.id
    ):
        cur = await get_user_language(callback.from_user.id)
        await callback.answer(t(cur, "lang_admins_only"), show_alert=True)
        return
    await set_user_language(callback.from_user.id, code)
    await callback.answer(t(code, "language_set"))
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_main_menu(callback.message, code)


# ─── Button: Admin (admin only) ─────────────────────────────
@router.message(F.text.func(lambda txt: txt and any(
    txt == t(code, "btn_admin") for code in LANGUAGES
)))
async def btn_admin(message: Message):
    if message.chat.type != "private" or message.from_user.id != config.ADMIN_ID:
        return
    from handlers.admin import cmd_admin
    await cmd_admin(message)


# ─── Button: Add bot to (group / channel) ───────────────────────────────────
@router.message(F.text.func(lambda txt: txt and any(
    txt == t(code, "btn_add_bot") for code in LANGUAGES
)))
async def btn_add_bot(message: Message):
    if not await _buttons_allowed(message):
        return
    lang = await get_user_language(message.from_user.id)
    # One button leads here; user then picks group or channel.
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    username = (await message.bot.me()).username
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t(lang, "btn_add_group"),
            url=f"https://t.me/{username}?startgroup=true"
        )],
        [InlineKeyboardButton(
            text=t(lang, "btn_add_channel"),
            url=f"https://t.me/{username}?startchannel=true"
        )],
    ])
    await message.answer(t(lang, "add_group_help"), parse_mode="HTML", reply_markup=kb)


# Keep /help and /stats as fallback commands too
@router.message(Command("help"))
async def cmd_help(message: Message):
    lang = await get_user_language(message.from_user.id)
    await message.answer(t(lang, "help"), parse_mode="HTML")


@router.message(Command("language"))
async def cmd_language(message: Message):
    # Private chats: anyone may change their own language.
    # Groups/channels: only chat admins may change it.
    await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    if message.chat.type != "private":
        if not await _is_group_admin(message.bot, message.chat.id, message.from_user.id):
            lang = await get_user_language(message.from_user.id)
            await message.reply(t(lang, "lang_admins_only"))
            return
    await _open_language(message)
