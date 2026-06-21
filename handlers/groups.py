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
    list_active_groups, claim_group,
    toggle_group_flag, set_group_download_mode,
)
from services.i18n import t, LANGUAGES
from keyboards.inline import (
    groups_list_keyboard, group_settings_keyboard, group_mode_keyboard,
)

router = Router()

_GROUP_TYPES = ("group", "supergroup", "channel")
_ADMIN_STATUSES = ("administrator", "creator")


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


async def _user_manageable_groups(bot, user_id: int) -> list:
    """Groups the user may configure: ones they added, plus any active group
    where they are currently an admin/creator. Unattributed groups they admin
    get claimed so they list instantly next time."""
    groups = await list_active_groups()
    out = []
    for g in groups:
        if g.get("added_by") == user_id:
            out.append(g)
            continue
        try:
            member = await bot.get_chat_member(g["chat_id"], user_id)
        except Exception:
            continue
        if getattr(member, "status", None) in _ADMIN_STATUSES:
            out.append(g)
            if g.get("added_by") is None:
                try:
                    await claim_group(g["chat_id"], user_id)
                except Exception:
                    pass
    return out


# ─── Track bot membership in groups/channels ────────────────
@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def bot_added(event: ChatMemberUpdated):
    """Bot was added / promoted in a group or channel."""
    if event.chat.type not in _GROUP_TYPES:
        return
    adder = event.from_user.id if event.from_user else None
    if adder:
        # Make sure the adder exists as a user so their /settings list works.
        await get_or_create_user(
            adder,
            event.from_user.username,
            event.from_user.first_name,
        )
    await ensure_group_chat(
        event.chat.id, event.chat.title, event.chat.type, added_by=adder
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


# ─── Callback router for per-group settings (gset:) ─────────
async def _can_manage(callback: CallbackQuery, g: dict) -> bool:
    """The adder may always manage; otherwise check live group-admin status."""
    uid = callback.from_user.id
    if g.get("added_by") == uid:
        return True
    try:
        member = await callback.bot.get_chat_member(g["chat_id"], uid)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


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

    else:
        await callback.answer()
