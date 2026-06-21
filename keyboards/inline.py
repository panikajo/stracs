from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from config import config
from services.i18n import t, LANGUAGES


def main_menu_keyboard(lang: str = "en", show_buy: bool = True, show_language: bool = True, is_admin: bool = False, show_settings: bool = True) -> ReplyKeyboardMarkup:
    """Persistent reply-keyboard menu shown to users (buttons instead of commands)."""
    rows = [[KeyboardButton(text=t(lang, "btn_help")), KeyboardButton(text=t(lang, "btn_stats"))]]
    last = []
    if show_buy:
        last.append(KeyboardButton(text=t(lang, "btn_buy")))
    if show_language:
        last.append(KeyboardButton(text=t(lang, "btn_language")))
    if last:
        rows.append(last)
    if show_settings:
        rows.append([KeyboardButton(text=t(lang, "btn_settings"))])
    # Add bot to group/channel (single button -> inline group/channel choice)
    rows.append([KeyboardButton(text=t(lang, "btn_add_bot"))])
    if is_admin:
        rows.append([KeyboardButton(text=t(lang, "btn_admin"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def language_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=name, callback_data=f"lang:{code}")]
            for code, name in LANGUAGES.items()]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── Per-user settings menu ─────────────────────────────────
# Mapping of stored mode value -> i18n label key.
_CAPTION_KEYS = {
    "src_via": "cap_src_via",
    "src": "cap_src",
    "src_plus": "cap_src_plus",
    "author": "cap_author",
    "off": "cap_off",
}
_DESC_KEYS = {
    "off": "desc_off",
    "separate": "desc_separate",
    "with": "desc_with",
    "quote": "desc_quote",
    "country": "desc_country",
}
_GALLERY_KEYS = {
    "photos": "gal_photos",
    "video": "gal_video",
}
_AUDIO_KEYS = {
    "off": "aud_off",
    "separate": "aud_separate",
}


def settings_keyboard(lang: str, settings: dict) -> InlineKeyboardMarkup:
    """Build the personal ⚙️ settings panel.

    `settings` is the dict returned by db.get_user_settings():
      {language, show_tags(bool), show_source_channel(bool), download_mode}
    """
    on = t(lang, "opt_on")
    off = t(lang, "opt_off")
    cur_lang = LANGUAGES.get(settings.get("language", "en"), settings.get("language", "en"))
    mode_label = t(lang, {
        "ask": "mode_ask",
        "video": "mode_video",
        "audio": "mode_audio",
    }.get(settings.get("download_mode", "ask"), "mode_ask"))

    rows = [
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_language')}: {cur_lang}",
            callback_data="uset:lang",
        )],
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_tags')}: {on if settings.get('show_tags') else off}",
            callback_data="uset:toggle:show_tags",
        )],
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_channel')}: {on if settings.get('show_source_channel') else off}",
            callback_data="uset:toggle:show_source_channel",
        )],
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_mode')}: {mode_label}",
            callback_data="uset:mode",
        )],
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_watermark')}: {on if settings.get('tiktok_watermark') else off}",
            callback_data="uset:toggle:tiktok_watermark",
        )],
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_caption')}: {t(lang, _CAPTION_KEYS.get(settings.get('caption_mode', 'src_via'), 'cap_src_via'))}",
            callback_data="uset:caption",
        )],
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_desc')}: {t(lang, _DESC_KEYS.get(settings.get('description_mode', 'off'), 'desc_off'))}",
            callback_data="uset:desc",
        )],
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_gallery')}: {t(lang, _GALLERY_KEYS.get(settings.get('gallery_mode', 'photos'), 'gal_photos'))}",
            callback_data="uset:cycle:gallery",
        )],
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_audio')}: {t(lang, _AUDIO_KEYS.get(settings.get('audio_mode', 'off'), 'aud_off'))}",
            callback_data="uset:cycle:audio",
        )],
        [InlineKeyboardButton(
            text=t(lang, "btn_my_groups"),
            callback_data="gset:list",
        )],
        [InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="uset:close")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_language_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Language picker shown from inside the settings panel (returns to it)."""
    rows = [[InlineKeyboardButton(text=name, callback_data=f"uset:setlang:{code}")]
            for code, name in LANGUAGES.items()]
    rows.append([InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="uset:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_mode_keyboard(lang: str, current: str) -> InlineKeyboardMarkup:
    """Download-mode picker (ask / video / audio), returns to settings panel."""
    mark = "\u2713 "
    rows = []
    for mode, key in (("ask", "mode_ask"), ("video", "mode_video"), ("audio", "mode_audio")):
        prefix = mark if current == mode else ""
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{t(lang, key)}",
            callback_data=f"uset:setmode:{mode}",
        )])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="uset:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_caption_keyboard(lang: str, current: str) -> InlineKeyboardMarkup:
    """Picker for the credit line under the content."""
    mark = "\u2713 "
    rows = []
    for mode, key in (
        ("src_via", "cap_src_via"),
        ("src", "cap_src"),
        ("src_plus", "cap_src_plus"),
        ("author", "cap_author"),
        ("off", "cap_off"),
    ):
        prefix = mark if current == mode else ""
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{t(lang, key)}",
            callback_data=f"uset:setcaption:{mode}",
        )])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="uset:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_description_keyboard(lang: str, current: str) -> InlineKeyboardMarkup:
    """Picker for how the post description/text is delivered."""
    mark = "\u2713 "
    rows = []
    for mode, key in (
        ("off", "desc_off"),
        ("separate", "desc_separate"),
        ("with", "desc_with"),
        ("quote", "desc_quote"),
        ("country", "desc_country"),
    ):
        prefix = mark if current == mode else ""
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{t(lang, key)}",
            callback_data=f"uset:setdesc:{mode}",
        )])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="uset:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── Per-group settings ─────────────────────────────────────
def groups_list_keyboard(lang: str, groups: list) -> InlineKeyboardMarkup:
    """List of groups/chats the user added the bot to."""
    rows = []
    for g in groups:
        rows.append([InlineKeyboardButton(
            text=f"\U0001F465 {g['title']}",
            callback_data=f"gset:open:{g['chat_id']}",
        )])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="gset:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_settings_keyboard(lang: str, settings: dict) -> InlineKeyboardMarkup:
    """Per-group settings panel: hashtags / source channel / mode / delete-url."""
    on = t(lang, "opt_on")
    off = t(lang, "opt_off")
    cid = settings["chat_id"]
    mode_label = t(lang, {
        "ask": "mode_ask", "video": "mode_video", "audio": "mode_audio",
    }.get(settings.get("download_mode", "ask"), "mode_ask"))

    rows = [
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_tags')}: {on if settings.get('show_tags') else off}",
            callback_data=f"gset:toggle:{cid}:show_tags",
        )],
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_channel')}: {on if settings.get('show_source_channel') else off}",
            callback_data=f"gset:toggle:{cid}:show_source_channel",
        )],
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_mode')}: {mode_label}",
            callback_data=f"gset:mode:{cid}",
        )],
        [InlineKeyboardButton(
            text=f"{t(lang, 'set_opt_delete_url')}: {on if settings.get('delete_user_url') else off}",
            callback_data=f"gset:toggle:{cid}:delete_user_url",
        )],
        [
            InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="gset:list"),
            InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="gset:close"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_mode_keyboard(lang: str, current: str, chat_id: int) -> InlineKeyboardMarkup:
    """Download-mode picker for a specific group, returns to its panel."""
    mark = "\u2713 "
    rows = []
    for mode, key in (("ask", "mode_ask"), ("video", "mode_video"), ("audio", "mode_audio")):
        prefix = mark if current == mode else ""
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{t(lang, key)}",
            callback_data=f"gset:setmode:{chat_id}:{mode}",
        )])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"gset:open:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quality_keyboard(short_id: str, platform: str) -> InlineKeyboardMarkup:
    buttons = []
    if platform in ("youtube", "unknown"):
        buttons.append([
            InlineKeyboardButton(text="📱 480p (Free)", callback_data=f"dl:480:{short_id}"),
        ])
        buttons.append([
            InlineKeyboardButton(text="🎵 Audio MP3 ⭐2", callback_data=f"pm:audio:{short_id}"),
            InlineKeyboardButton(text="🎬 720p ⭐3", callback_data=f"pm:720:{short_id}"),
        ])
        buttons.append([
            InlineKeyboardButton(text="🔥 1080p ⭐5", callback_data=f"pm:1080:{short_id}"),
            InlineKeyboardButton(text="⭐ 4K Best ⭐10", callback_data=f"pm:4k:{short_id}"),
        ])
    elif platform == "tiktok":
        buttons.append([
            InlineKeyboardButton(text="🎬 Video", callback_data=f"dl:best:{short_id}"),
            InlineKeyboardButton(text="🎵 Audio Only", callback_data=f"dl:audio:{short_id}"),
        ])
    elif platform == "instagram":
        buttons.append([
            InlineKeyboardButton(text="📥 Download", callback_data=f"dl:best:{short_id}"),
        ])
    buttons.append([
        InlineKeyboardButton(text="❌ Cancel", callback_data="cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel Download", callback_data="cancel")]
    ])


def buy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⭐ Buy {config.STARS_EXTRA_DOWNLOADS} extra downloads",
            callback_data="buy_stars"
        )]
    ])
