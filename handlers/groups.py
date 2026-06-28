"""Per-group settings.

When the bot is added to a group/channel we record it (and who added it).
The adder can then open "My groups" in their private chat (⚙️ Settings →
👥 My groups, or /mygroups) and configure, per group:
  • source hashtags in the caption
  • source channel/author in the caption
  • download mode (ask / video / audio)
  • whether to delete the user's link message after the download is sent
"""
from aiogram import Router, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION, LEAVE_TRANSITION

from database.db import (
    get_or_create_user, get_user_language, get_setting,
    ensure_group_chat, set_group_inactive, get_group_settings,
    list_active_groups,
    toggle_group_flag, set_group_download_mode, set_group_description_mode,
    set_group_caption_mode, set_group_language,
)
from services.i18n import t, LANGUAGES
from keyboards.inline import (
    groups_list_keyboard, group_settings_keyboard, group_mode_keyboard,
    group_description_keyboard, group_caption_keyboard, group_language_keyboard,
)

router = Router()

_GROUP_TYPES = ("group", "supergroup", "channel")
_CREATOR_STATUS = "creator"


# ─── Auto-register any group/channel the bot is active in ───
class GroupRegistrationMiddleware(BaseMiddleware):
    """Records groups/channels the bot sees activity in.

    Telegram offers no way to list the chats a bot belongs to, and groups the
    bot joined *before* this feature shipped never fired a my_chat_member event.
    So we lazily register a chat the first time we observe any message/post in
    it (added_by stays unknown — it gets attributed to the first admin who
    opens its settings). An in-memory cache keeps this to one DB write per chat
    per process lifetime.
    """

    def __init__(self):
        self._seen: set[int] = set()

    async def __call__(self, handler, event, data):
        chat = getattr(event, "chat", None)
        if chat is not None and chat.type in _GROUP_TYPES and chat.id not in self._seen:
            self._seen.add(chat.id)
            try:
                await ensure_group_chat(chat.id, chat.title, chat.type)
            except Exception:
                pass
        return await handler(event, data)


def register_group_middleware(dp):
    """Attach the lazy group-registration middleware to a Dispatcher."""
    mw = GroupRegistrationMiddleware()
    dp.message.outer_middleware(mw)
    dp.channel_post.outer_middleware(mw)
    dp.edited_message.outer_middleware(mw)


async def _is_chat_creator(bot, chat_id: int, user_id: int) -> bool:
    """Return True only for the real Telegram group/channel owner.

    Administrators must not see or manage the chat in "My groups"; the owner
    has member.status == "creator" in Telegram Bot API / aiogram.
    """
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return getattr(member, "status", None) == _CREATOR_STATUS
    except Exception:
        return False


async def _user_manageable_groups(bot, user_id: int) -> list:
    """Groups/chats this user may configure.

    Show a group only to its real Telegram creator/owner, not to every admin.
    This intentionally ignores historical added_by values when the user is no
    longer the current creator, because admins can also add bots.
    """
    groups = await list_active_groups()
    out = []
    for g in groups:
        if await _is_chat_creator(bot, g["chat_id"], user_id):
            out.append(g)
    return out


# ─── Track bot membership in groups/channels ────────────────
@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def bot_added(event: ChatMemberUpdated):
    """Bot was added / promoted in a group or channel."""
    if event.chat.type not in _GROUP_TYPES:
        return
    adder = event.from_user.id if event.from_user else None
    owner_id = None
    group_lang = None
    if adder:
        # Make sure the triggering user exists, but only store them as owner if
        # Telegram says they are the real chat creator. Admins can add bots too.
        await get_or_create_user(
            adder,
            event.from_user.username,
            event.from_user.first_name,
        )
        if await _is_chat_creator(event.bot, event.chat.id, adder):
            owner_id = adder
            group_lang = await get_user_language(adder)
    await ensure_group_chat(
        event.chat.id, event.chat.title, event.chat.type, added_by=owner_id, language=group_lang
    )


@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION))
async def bot_removed(event: ChatMemberUpdated):
    """Bot was removed / kicked from a group or channel."""
    if event.chat.type not in _GROUP_TYPES:
        return
    await set_group_inactive(event.chat.id)


# ─── Entry points (private only) ────────────────────────────
async def _show_group_list(message: Message):
    await get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.first_name
    )
    lang = await get_user_language(message.from_user.id)
    groups = await _user_manageable_groups(message.bot, message.from_user.id)
    if not groups:
        await message.answer(t(lang, "my_groups_empty"), parse_mode="HTML")
        return
    await message.answer(
        t(lang, "my_groups_title"),
        parse_mode="HTML",
        reply_markup=groups_list_keyboard(lang, groups),
    )


@router.message(Command("mygroups"))
async def cmd_mygroups(message: Message):
    if message.chat.type != "private":
        return
    await _show_group_list(message)


@router.message(Command("registergroup", "registerchat"))
async def cmd_register_group(message: Message):
    """Manually bind the current group/chat to the admin after moving hosting/DB.

    Telegram does not provide historical bot group membership. If the bot is
    moved to a new server with an empty DB, admins can send /registergroup in
    each group so it appears again in their private "My groups" list.
    """
    if message.chat.type not in _GROUP_TYPES:
        await message.answer("Эту команду нужно отправить внутри группы/чата, который нужно привязать.")
        return
    if not message.from_user:
        return

    try:
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        if getattr(member, "status", None) != _CREATOR_STATUS:
            await message.answer("❌ Привязать группу может только создатель/владелец этой группы, не обычный админ.")
            return
    except Exception:
        await message.answer("❌ Не смог проверить, что вы создатель этой группы.")
        return

    await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await ensure_group_chat(
        message.chat.id,
        message.chat.title or str(message.chat.id),
        message.chat.type,
        added_by=message.from_user.id,
        language=await get_user_language(message.from_user.id),
    )
    await message.answer(
        "✅ Группа привязана. Теперь откройте личный чат с ботом → ⚙️ Настройки → 👥 Мои группы/чаты."
    )


# ─── Callback router for per-group settings (gset:) ─────────
async def _can_manage(callback: CallbackQuery, g: dict) -> bool:
    """Only the real Telegram creator/owner may manage group settings."""
    return await _is_chat_creator(callback.bot, g["chat_id"], callback.from_user.id)


async def _render_group_list(callback: CallbackQuery, lang: str):
    groups = await _user_manageable_groups(callback.bot, callback.from_user.id)
    if not groups:
        try:
            await callback.message.edit_text(t(lang, "my_groups_empty"), parse_mode="HTML")
        except Exception:
            pass
        return
    try:
        await callback.message.edit_text(
            t(lang, "my_groups_title"),
            parse_mode="HTML",
            reply_markup=groups_list_keyboard(lang, groups),
        )
    except Exception:
        pass


async def _render_group_panel(callback: CallbackQuery, lang: str, g: dict):
    try:
        await callback.message.edit_text(
            t(lang, "group_settings_title", title=g["title"]),
            parse_mode="HTML",
            reply_markup=group_settings_keyboard(lang, g),
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("gset:"))
async def group_callbacks(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    parts = callback.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "close":
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer()
        return

    if action == "list":
        await _render_group_list(callback, lang)
        await callback.answer()
        return

    # Remaining actions operate on a specific chat_id (parts[2]).
    if len(parts) < 3:
        await callback.answer()
        return
    try:
        chat_id = int(parts[2])
    except ValueError:
        await callback.answer()
        return

    g = await get_group_settings(chat_id)
    if not g or not g["is_active"]:
        await callback.answer(t(lang, "group_no_access"), show_alert=True)
        await _render_group_list(callback, lang)
        return
    if not await _can_manage(callback, g):
        await callback.answer(t(lang, "group_no_access"), show_alert=True)
        return

    if action == "open":
        await _render_group_panel(callback, lang, g)
        await callback.answer()

    elif action == "toggle":
        field = parts[3] if len(parts) > 3 else ""
        try:
            await toggle_group_flag(chat_id, field)
        except ValueError:
            await callback.answer()
            return
        g = await get_group_settings(chat_id)
        await _render_group_panel(callback, lang, g)
        await callback.answer(t(lang, "setting_saved"))

    elif action == "mode":
        try:
            await callback.message.edit_text(
                t(lang, "choose_mode"),
                parse_mode="HTML",
                reply_markup=group_mode_keyboard(lang, g["download_mode"], chat_id),
            )
        except Exception:
            pass
        await callback.answer()

    elif action == "setmode":
        mode = parts[3] if len(parts) > 3 else "ask"
        await set_group_download_mode(chat_id, mode)
        g = await get_group_settings(chat_id)
        await _render_group_panel(callback, lang, g)
        await callback.answer(t(lang, "setting_saved"))

    elif action == "lang":
        try:
            await callback.message.edit_text(
                t(lang, "choose_language"),
                parse_mode="HTML",
                reply_markup=group_language_keyboard(lang, g.get("language", "en"), chat_id),
            )
        except Exception:
            pass
        await callback.answer()

    elif action == "setlang":
        code = parts[3] if len(parts) > 3 else "en"
        if code not in LANGUAGES:
            code = "en"
        await set_group_language(chat_id, code)
        g = await get_group_settings(chat_id)
        await _render_group_panel(callback, lang, g)
        await callback.answer(t(lang, "setting_saved"))

    elif action == "caption":
        try:
            await callback.message.edit_text(
                t(lang, "choose_caption"),
                parse_mode="HTML",
                reply_markup=group_caption_keyboard(lang, g.get("caption_mode", "src_via"), chat_id),
            )
        except Exception:
            pass
        await callback.answer()

    elif action == "setcaption":
        mode = parts[3] if len(parts) > 3 else "src_via"
        await set_group_caption_mode(chat_id, mode)
        g = await get_group_settings(chat_id)
        await _render_group_panel(callback, lang, g)
        await callback.answer(t(lang, "setting_saved"))

    elif action == "desc":
        try:
            await callback.message.edit_text(
                t(lang, "choose_desc"),
                parse_mode="HTML",
                reply_markup=group_description_keyboard(lang, g.get("description_mode", "off"), chat_id),
            )
        except Exception:
            pass
        await callback.answer()

    elif action == "setdesc":
        mode = parts[3] if len(parts) > 3 else "off"
        await set_group_description_mode(chat_id, mode)
        g = await get_group_settings(chat_id)
        await _render_group_panel(callback, lang, g)
        await callback.answer(t(lang, "setting_saved"))

    else:
        await callback.answer()
