"""Per-user settings menu: language, source hashtags, source channel,
default download mode. Opened via the ⚙️ button or /settings."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.db import (
    get_or_create_user, get_user_language, set_user_language,
    get_user_settings, toggle_user_flag, set_user_download_mode, get_setting,
    set_user_description_mode, set_user_caption_mode,
    set_user_gallery_mode, set_user_audio_mode,
    VALID_GALLERY_MODES, VALID_AUDIO_MODES,
)
from services.i18n import t, LANGUAGES
from keyboards.inline import (
    settings_keyboard, settings_language_keyboard, settings_mode_keyboard,
    settings_caption_keyboard, settings_description_keyboard,
)

router = Router()


async def _settings_enabled() -> bool:
    """Admin master switch for the whole personal settings menu."""
    return await get_setting("feature_user_settings", "1") == "1"


async def _open_settings_message(message: Message):
    """Show the settings panel as a fresh message (command / button entry)."""
    await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    lang = await get_user_language(message.from_user.id)
    if not await _settings_enabled():
        await message.answer(t(lang, "feature_disabled"))
        return
    settings = await get_user_settings(message.from_user.id)
    await message.answer(
        t(lang, "settings_title"),
        parse_mode="HTML",
        reply_markup=settings_keyboard(lang, settings),
    )


# ─── Entry points: /settings command + ⚙️ button ───────────
@router.message(Command("settings"))
async def cmd_settings(message: Message):
    if message.chat.type != "private":
        return
    await _open_settings_message(message)


@router.message(F.text.func(lambda txt: txt and any(
    txt == t(code, "btn_settings") for code in LANGUAGES
)))
async def btn_settings(message: Message):
    if message.chat.type != "private":
        return
    await _open_settings_message(message)


# ─── Callback router for the settings panel ─────────────────
async def _render_panel(callback: CallbackQuery, lang: str):
    settings = await get_user_settings(callback.from_user.id)
    try:
        await callback.message.edit_text(
            t(lang, "settings_title"),
            parse_mode="HTML",
            reply_markup=settings_keyboard(lang, settings),
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("uset:"))
async def settings_callbacks(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)

    if not await _settings_enabled():
        await callback.answer(t(lang, "feature_disabled"), show_alert=True)
        return

    parts = callback.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "back":
        await _render_panel(callback, lang)
        await callback.answer()

    elif action == "close":
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer()

    elif action == "toggle":
        field = parts[2] if len(parts) > 2 else ""
        try:
            await toggle_user_flag(callback.from_user.id, field)
        except ValueError:
            await callback.answer()
            return
        await _render_panel(callback, lang)
        await callback.answer(t(lang, "setting_saved"))

    elif action == "lang":
        try:
            await callback.message.edit_text(
                t(lang, "choose_language"),
                reply_markup=settings_language_keyboard(lang),
            )
        except Exception:
            pass
        await callback.answer()

    elif action == "setlang":
        code = parts[2] if len(parts) > 2 else ""
        if code in LANGUAGES:
            await set_user_language(callback.from_user.id, code)
            lang = code
            await callback.answer(t(lang, "language_set"))
        else:
            await callback.answer()
        await _render_panel(callback, lang)

    elif action == "mode":
        settings = await get_user_settings(callback.from_user.id)
        try:
            await callback.message.edit_text(
                t(lang, "choose_mode"),
                parse_mode="HTML",
                reply_markup=settings_mode_keyboard(lang, settings["download_mode"]),
            )
        except Exception:
            pass
        await callback.answer()

    elif action == "setmode":
        mode = parts[2] if len(parts) > 2 else "ask"
        await set_user_download_mode(callback.from_user.id, mode)
        await _render_panel(callback, lang)
        await callback.answer(t(lang, "setting_saved"))

    elif action == "caption":
        settings = await get_user_settings(callback.from_user.id)
        try:
            await callback.message.edit_text(
                t(lang, "choose_caption"),
                parse_mode="HTML",
                reply_markup=settings_caption_keyboard(lang, settings["caption_mode"]),
            )
        except Exception:
            pass
        await callback.answer()

    elif action == "setcaption":
        mode = parts[2] if len(parts) > 2 else "src_via"
        await set_user_caption_mode(callback.from_user.id, mode)
        await _render_panel(callback, lang)
        await callback.answer(t(lang, "setting_saved"))

    elif action == "desc":
        settings = await get_user_settings(callback.from_user.id)
        try:
            await callback.message.edit_text(
                t(lang, "choose_desc"),
                parse_mode="HTML",
                reply_markup=settings_description_keyboard(lang, settings["description_mode"]),
            )
        except Exception:
            pass
        await callback.answer()

    elif action == "setdesc":
        mode = parts[2] if len(parts) > 2 else "off"
        await set_user_description_mode(callback.from_user.id, mode)
        await _render_panel(callback, lang)
        await callback.answer(t(lang, "setting_saved"))

    elif action == "cycle":
        # Two-value settings toggled in place.
        which = parts[2] if len(parts) > 2 else ""
        settings = await get_user_settings(callback.from_user.id)
        if which == "gallery":
            cur = settings.get("gallery_mode", "photos")
            nxt = VALID_GALLERY_MODES[(VALID_GALLERY_MODES.index(cur) + 1) % len(VALID_GALLERY_MODES)] \
                if cur in VALID_GALLERY_MODES else VALID_GALLERY_MODES[0]
            await set_user_gallery_mode(callback.from_user.id, nxt)
        elif which == "audio":
            cur = settings.get("audio_mode", "off")
            nxt = VALID_AUDIO_MODES[(VALID_AUDIO_MODES.index(cur) + 1) % len(VALID_AUDIO_MODES)] \
                if cur in VALID_AUDIO_MODES else VALID_AUDIO_MODES[0]
            await set_user_audio_mode(callback.from_user.id, nxt)
        await _render_panel(callback, lang)
        await callback.answer(t(lang, "setting_saved"))

    else:
        await callback.answer()
