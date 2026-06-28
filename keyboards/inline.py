from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from config import config
from services.i18n import t, LANGUAGES


I18N_FALLBACKS = {
    "ru": {
        "set_opt_language": "🌐 Язык",
        "set_opt_group_language": "🌐 Язык бота в чате",
        "set_opt_tags": "#️⃣ Хештеги",
        "set_opt_channel": "👤 Канал источника",
        "set_opt_mode": "🎬 Режим загрузки",
        "set_opt_watermark": "💧 TikTok watermark",
        "set_opt_caption": "🎬 Джерело ✦ Via",
        "set_opt_desc": "📝 Описание источника",
        "set_opt_gallery": "🖼 Галереи/фото",
        "set_opt_audio": "🎵 Аудио из фото",
        "set_opt_delete_url": "🗑 Удалять ссылку юзера",
        "opt_on": "✅ Вкл",
        "opt_off": "❌ Выкл",
        "cap_src_via": "Джерело ✦ Via",
        "cap_src": "Только источник",
        "cap_src_plus": "Источник+",
        "cap_author": "Только автор",
        "cap_off": "Выключено",
        "desc_off": "Выключено",
        "desc_separate": "Отдельным сообщением",
        "desc_with": "Вместе с подписью",
        "desc_quote": "Цитатой",
        "desc_country": "Страна/гео",
        "gal_photos": "Фото/альбом",
        "gal_video": "Видео-слайдшоу",
        "aud_off": "Выключено",
        "aud_separate": "Отдельным файлом",
        "btn_my_groups": "👥 Мои группы/чаты",
        "btn_close": "✖️ Закрыть",
        "btn_back": "⬅️ Назад",
        "mode_ask": "❓ Спрашивать каждый раз",
        "mode_video": "🎥 Видео",
        "mode_audio": "🎵 Аудио",
    },
    "uk": {
        "set_opt_language": "🌐 Мова",
        "set_opt_group_language": "🌐 Мова бота в чаті",
        "set_opt_tags": "#️⃣ Хештеги",
        "set_opt_channel": "👤 Канал джерела",
        "set_opt_mode": "🎬 Режим завантаження",
        "set_opt_watermark": "💧 TikTok watermark",
        "set_opt_caption": "🎬 Джерело ✦ Via",
        "set_opt_desc": "📝 Опис джерела",
        "set_opt_gallery": "🖼 Галереї/фото",
        "set_opt_audio": "🎵 Аудіо з фото",
        "set_opt_delete_url": "🗑 Видаляти посилання юзера",
        "opt_on": "✅ Увімк",
        "opt_off": "❌ Вимк",
        "cap_src_via": "Джерело ✦ Via",
        "cap_src": "Тільки джерело",
        "cap_src_plus": "Джерело+",
        "cap_author": "Тільки автор",
        "cap_off": "Вимкнено",
        "desc_off": "Вимкнено",
        "desc_separate": "Окремим повідомленням",
        "desc_with": "Разом з підписом",
        "desc_quote": "Цитатою",
        "desc_country": "Країна/гео",
        "gal_photos": "Фото/альбом",
        "gal_video": "Відео-слайдшоу",
        "aud_off": "Вимкнено",
        "aud_separate": "Окремим файлом",
        "btn_my_groups": "👥 Мої групи/чати",
        "btn_close": "✖️ Закрити",
        "btn_back": "⬅️ Назад",
        "mode_ask": "❓ Запитувати щоразу",
        "mode_video": "🎥 Відео",
        "mode_audio": "🎵 Аудіо",
    },
    "en": {
        "set_opt_language": "🌐 Language",
        "set_opt_group_language": "🌐 Bot language in chat",
        "set_opt_tags": "#️⃣ Hashtags",
        "set_opt_channel": "👤 Source channel",
        "set_opt_mode": "🎬 Download mode",
        "set_opt_watermark": "💧 TikTok watermark",
        "set_opt_caption": "🎬 Source ✦ Via",
        "set_opt_desc": "📝 Source description",
        "set_opt_gallery": "🖼 Galleries/photos",
        "set_opt_audio": "🎵 Photo audio",
        "set_opt_delete_url": "🗑 Delete user URL",
        "opt_on": "✅ On",
        "opt_off": "❌ Off",
        "cap_src_via": "Source ✦ Via",
        "cap_src": "Source only",
        "cap_src_plus": "Source+",
        "cap_author": "Author only",
        "cap_off": "Off",
        "desc_off": "Off",
        "desc_separate": "Separate message",
        "desc_with": "With caption",
        "desc_quote": "Quote",
        "desc_country": "Country/geo",
        "gal_photos": "Photos/album",
        "gal_video": "Video slideshow",
        "aud_off": "Off",
        "aud_separate": "Separate file",
        "btn_my_groups": "👥 My groups/chats",
        "btn_close": "✖️ Close",
        "btn_back": "⬅️ Back",
        "mode_ask": "❓ Ask every time",
        "mode_video": "🎥 Video",
        "mode_audio": "🎵 Audio",
    },
}


def tr(lang: str, key: str) -> str:
    """Translate with built-in fallback so missing i18n keys don't leak to UI."""
    value = t(lang, key)
    if value != key:
        return value
    return I18N_FALLBACKS.get(lang, I18N_FALLBACKS["en"]).get(key, key)


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
    on = tr(lang, "opt_on")
    off = tr(lang, "opt_off")
    cur_lang = LANGUAGES.get(settings.get("language", "en"), settings.get("language", "en"))
    mode_label = tr(lang, {
        "ask": "mode_ask",
        "video": "mode_video",
        "audio": "mode_audio",
    }.get(settings.get("download_mode", "ask"), "mode_ask"))

    rows = [
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_language')}: {cur_lang}",
            callback_data="uset:lang",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_tags')}: {on if settings.get('show_tags') else off}",
            callback_data="uset:toggle:show_tags",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_channel')}: {on if settings.get('show_source_channel') else off}",
            callback_data="uset:toggle:show_source_channel",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_mode')}: {mode_label}",
            callback_data="uset:mode",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_watermark')}: {on if settings.get('tiktok_watermark') else off}",
            callback_data="uset:toggle:tiktok_watermark",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_caption')}: {tr(lang, _CAPTION_KEYS.get(settings.get('caption_mode', 'src_via'), 'cap_src_via'))}",
            callback_data="uset:caption",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_desc')}: {tr(lang, _DESC_KEYS.get(settings.get('description_mode', 'off'), 'desc_off'))}",
            callback_data="uset:desc",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_gallery')}: {tr(lang, _GALLERY_KEYS.get(settings.get('gallery_mode', 'photos'), 'gal_photos'))}",
            callback_data="uset:cycle:gallery",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_audio')}: {tr(lang, _AUDIO_KEYS.get(settings.get('audio_mode', 'off'), 'aud_off'))}",
            callback_data="uset:cycle:audio",
        )],
        [InlineKeyboardButton(
            text=tr(lang, "btn_my_groups"),
            callback_data="gset:list",
        )],
        [InlineKeyboardButton(text=tr(lang, "btn_close"), callback_data="uset:close")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_language_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Language picker shown from inside the settings panel (returns to it)."""
    rows = [[InlineKeyboardButton(text=name, callback_data=f"uset:setlang:{code}")]
            for code, name in LANGUAGES.items()]
    rows.append([InlineKeyboardButton(text=tr(lang, "btn_back"), callback_data="uset:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_mode_keyboard(lang: str, current: str) -> InlineKeyboardMarkup:
    """Download-mode picker (ask / video / audio), returns to settings panel."""
    mark = "\u2713 "
    rows = []
    for mode, key in (("ask", "mode_ask"), ("video", "mode_video"), ("audio", "mode_audio")):
        prefix = mark if current == mode else ""
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{tr(lang, key)}",
            callback_data=f"uset:setmode:{mode}",
        )])
    rows.append([InlineKeyboardButton(text=tr(lang, "btn_back"), callback_data="uset:back")])
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
            text=f"{prefix}{tr(lang, key)}",
            callback_data=f"uset:setcaption:{mode}",
        )])
    rows.append([InlineKeyboardButton(text=tr(lang, "btn_back"), callback_data="uset:back")])
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
            text=f"{prefix}{tr(lang, key)}",
            callback_data=f"uset:setdesc:{mode}",
        )])
    rows.append([InlineKeyboardButton(text=tr(lang, "btn_back"), callback_data="uset:back")])
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
    rows.append([InlineKeyboardButton(text=tr(lang, "btn_close"), callback_data="gset:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_settings_keyboard(lang: str, settings: dict) -> InlineKeyboardMarkup:
    """Per-group settings panel: hashtags / source channel / mode / delete-url."""
    on = tr(lang, "opt_on")
    off = tr(lang, "opt_off")
    cid = settings["chat_id"]
    mode_label = tr(lang, {
        "ask": "mode_ask", "video": "mode_video", "audio": "mode_audio",
    }.get(settings.get("download_mode", "ask"), "mode_ask"))

    rows = [
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_tags')}: {on if settings.get('show_tags') else off}",
            callback_data=f"gset:toggle:{cid}:show_tags",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_channel')}: {on if settings.get('show_source_channel') else off}",
            callback_data=f"gset:toggle:{cid}:show_source_channel",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_mode')}: {mode_label}",
            callback_data=f"gset:mode:{cid}",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_group_language')}: {LANGUAGES.get(settings.get('language', 'en'), settings.get('language', 'en'))}",
            callback_data=f"gset:lang:{cid}",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_caption')}: {tr(lang, _CAPTION_KEYS.get(settings.get('caption_mode', 'src_via'), 'cap_src_via'))}",
            callback_data=f"gset:caption:{cid}",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_desc')}: {tr(lang, _DESC_KEYS.get(settings.get('description_mode', 'off'), 'desc_off'))}",
            callback_data=f"gset:desc:{cid}",
        )],
        [InlineKeyboardButton(
            text=f"{tr(lang, 'set_opt_delete_url')}: {on if settings.get('delete_user_url') else off}",
            callback_data=f"gset:toggle:{cid}:delete_user_url",
        )],
        [
            InlineKeyboardButton(text=tr(lang, "btn_back"), callback_data="gset:list"),
            InlineKeyboardButton(text=tr(lang, "btn_close"), callback_data="gset:close"),
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
            text=f"{prefix}{tr(lang, key)}",
            callback_data=f"gset:setmode:{chat_id}:{mode}",
        )])
    rows.append([InlineKeyboardButton(text=tr(lang, "btn_back"), callback_data=f"gset:open:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def group_language_keyboard(lang: str, current: str, chat_id: int) -> InlineKeyboardMarkup:
    """Language picker for a specific group/chat."""
    mark = "\u2713 "
    rows = []
    for code, name in LANGUAGES.items():
        prefix = mark if current == code else ""
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{name}",
            callback_data=f"gset:setlang:{chat_id}:{code}",
        )])
    rows.append([InlineKeyboardButton(text=tr(lang, "btn_back"), callback_data=f"gset:open:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_caption_keyboard(lang: str, current: str, chat_id: int) -> InlineKeyboardMarkup:
    """Credit-line picker for a specific group/chat."""
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
            text=f"{prefix}{tr(lang, key)}",
            callback_data=f"gset:setcaption:{chat_id}:{mode}",
        )])
    rows.append([InlineKeyboardButton(text=tr(lang, "btn_back"), callback_data=f"gset:open:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_description_keyboard(lang: str, current: str, chat_id: int) -> InlineKeyboardMarkup:
    """Description-mode picker for a specific group/chat."""
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
            text=f"{prefix}{tr(lang, key)}",
            callback_data=f"gset:setdesc:{chat_id}:{mode}",
        )])
    rows.append([InlineKeyboardButton(text=tr(lang, "btn_back"), callback_data=f"gset:open:{chat_id}")])
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
    elif platform in ("instagram", "threads"):
        label = "🧵 Download" if platform == "threads" else "📥 Download"
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"dl:best:{short_id}"),
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
