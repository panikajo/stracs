import json
import aiosqlite

try:
    import aiomysql
except ImportError:  # Optional unless DB_TYPE=mysql
    aiomysql = None

from datetime import date, datetime
from config import config


class CompatRow(dict):
    """Dict row that also supports row[0] like sqlite rows used in old code."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class CompatCursor:
    def __init__(self, lastrowid=None):
        self.lastrowid = lastrowid


class MySQLDB:
    def __init__(self, conn):
        self.conn = conn

    def _sql(self, sql: str) -> str:
        sql = sql.replace("?", "%s")
        sql = sql.replace("MAX(0, extra_downloads - 1)", "GREATEST(0, extra_downloads - 1)")
        return sql

    async def execute_fetchall(self, sql: str, params=()):
        async with self.conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(self._sql(sql), params or ())
            rows = await cur.fetchall()
        return [CompatRow(r) for r in rows]

    async def execute(self, sql: str, params=()):
        async with self.conn.cursor() as cur:
            await cur.execute(self._sql(sql), params or ())
            return CompatCursor(cur.lastrowid)

    async def commit(self):
        await self.conn.commit()

    async def close(self):
        self.conn.close()


async def get_db():
    if config.DB_TYPE == "mysql":
        if aiomysql is None:
            raise RuntimeError("DB_TYPE=mysql requires: pip install aiomysql")
        conn = await aiomysql.connect(
            host=config.MYSQL_HOST,
            port=config.MYSQL_PORT,
            user=config.MYSQL_USER,
            password=config.MYSQL_PASSWORD,
            db=config.MYSQL_DATABASE,
            charset=config.MYSQL_CHARSET,
            autocommit=False,
        )
        return MySQLDB(conn)

    db = await aiosqlite.connect(config.DB_PATH)
    db.row_factory = aiosqlite.Row
    return db

async def get_or_create_user(user_id: int, username: str = None, first_name: str = None):
    db = await get_db()
    try:
        today = date.today().isoformat()
        row = await db.execute_fetchall(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        if not row:
            await db.execute(
                "INSERT INTO users (user_id, username, first_name, last_reset) VALUES (?, ?, ?, ?)",
                (user_id, username, first_name, today)
            )
            await db.commit()
            return {"user_id": user_id, "downloads_today": 0, "daily_limit": config.DAILY_LIMIT, "extra_downloads": 0, "is_banned": 0}
        user = dict(row[0])
        # Reset daily counter if new day
        if user["last_reset"] != today:
            await db.execute(
                "UPDATE users SET downloads_today = 0, last_reset = ? WHERE user_id = ?",
                (today, user_id)
            )
            await db.commit()
            user["downloads_today"] = 0
        return user
    finally:
        await db.close()

async def can_download(user_id: int) -> tuple[bool, str]:
    user = await get_or_create_user(user_id)
    if user["is_banned"]:
        return False, "🚫 You are banned."
    limit = user["daily_limit"] or config.DAILY_LIMIT
    if user["daily_limit"] == 0:  # 0 = unlimited
        return True, ""
    used = user["downloads_today"]
    extra = user["extra_downloads"]
    remaining = limit - used + extra
    if remaining <= 0:
        return False, f"📭 Daily limit reached ({limit}/day).\n\n⭐ Buy {config.STARS_EXTRA_DOWNLOADS} extra downloads for {config.STARS_PRICE} Stars — /buy"
    return True, ""

async def record_download(user_id: int, url: str, platform: str, title: str = None, file_size: int = 0, chat_id: int = None):
    db = await get_db()
    try:
        today = date.today().isoformat()
        await db.execute(
            "INSERT INTO downloads (user_id, url, platform, title, file_size, chat_id) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, url, platform, title, file_size, chat_id)
        )

        # Check if user is over daily limit — use extra download instead
        user = await db.execute_fetchall("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if user:
            u = dict(user[0])
            daily_limit = u["daily_limit"] or config.DAILY_LIMIT
            if daily_limit > 0 and u["downloads_today"] >= daily_limit and u["extra_downloads"] > 0:
                # Use extra download
                await db.execute(
                    "UPDATE users SET extra_downloads = MAX(0, extra_downloads - 1) WHERE user_id = ?",
                    (user_id,)
                )
            else:
                # Normal daily counter
                await db.execute(
                    "UPDATE users SET downloads_today = downloads_today + 1 WHERE user_id = ?",
                    (user_id,)
                )

        # Update daily stats. Do it in Python so it works on both SQLite and MySQL.
        stat_rows = await db.execute_fetchall(
            "SELECT total_downloads, by_platform FROM stats WHERE date = ?",
            (today,),
        )
        if stat_rows:
            stat = dict(stat_rows[0])
            try:
                by_platform = json.loads(stat.get("by_platform") or "{}")
            except Exception:
                by_platform = {}
            by_platform[platform] = int(by_platform.get(platform, 0)) + 1
            await db.execute(
                "UPDATE stats SET total_downloads = total_downloads + 1, by_platform = ? WHERE date = ?",
                (json.dumps(by_platform, ensure_ascii=False), today),
            )
        else:
            await db.execute(
                "INSERT INTO stats (date, total_downloads, by_platform) VALUES (?, 1, ?)",
                (today, json.dumps({platform: 1}, ensure_ascii=False)),
            )
        await db.commit()
    finally:
        await db.close()

async def add_extra_downloads(user_id: int, count: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET extra_downloads = extra_downloads + ? WHERE user_id = ?",
            (count, user_id)
        )
        await db.commit()
    finally:
        await db.close()

async def use_extra_download(user_id: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET extra_downloads = MAX(0, extra_downloads - 1) WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()
    finally:
        await db.close()

async def get_chat_download_stats(chat_id: int) -> dict:
    """Per-chat download counts grouped by platform.

    Returns:
        {
          "today":       {platform: count, ...},
          "today_total": int,
          "total":       {platform: count, ...},
          "all_total":   int,
        }
    Counts only successfully recorded downloads (rows in `downloads`).
    """
    db = await get_db()
    try:
        today = date.today().isoformat()
        today_rows = await db.execute_fetchall(
            "SELECT platform, COUNT(*) FROM downloads "
            "WHERE chat_id = ? AND date(created_at) = ? GROUP BY platform",
            (chat_id, today),
        )
        total_rows = await db.execute_fetchall(
            "SELECT platform, COUNT(*) FROM downloads "
            "WHERE chat_id = ? GROUP BY platform",
            (chat_id,),
        )
        today = {(r[0] or "unknown"): r[1] for r in today_rows}
        total = {(r[0] or "unknown"): r[1] for r in total_rows}
        return {
            "today": today,
            "today_total": sum(today.values()),
            "total": total,
            "all_total": sum(total.values()),
        }
    finally:
        await db.close()


async def get_stats():
    db = await get_db()
    try:
        today = date.today().isoformat()
        total_users = await db.execute_fetchall("SELECT COUNT(*) FROM users")
        today_downloads = await db.execute_fetchall(
            "SELECT COUNT(*) FROM downloads WHERE date(created_at) = ?", (today,)
        )
        total_downloads = await db.execute_fetchall("SELECT COUNT(*) FROM downloads")
        return {
            "total_users": total_users[0][0],
            "today_downloads": today_downloads[0][0],
            "total_downloads": total_downloads[0][0],
        }
    finally:
        await db.close()

async def ban_user(user_id: int, ban: bool = True):
    db = await get_db()
    try:
        await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (1 if ban else 0, user_id))
        await db.commit()
    finally:
        await db.close()

async def get_all_users():
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM users ORDER BY created_at DESC")
        return [dict(r) for r in rows]
    finally:
        await db.close()

async def get_recent_downloads(limit: int = 50):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM downloads ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()

async def get_user_by_id(user_id: int):
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return dict(rows[0]) if rows else None
    finally:
        await db.close()

async def set_user_limit(user_id: int, limit: int):
    db = await get_db()
    try:
        await db.execute("UPDATE users SET daily_limit = ? WHERE user_id = ?", (limit, user_id))
        await db.commit()
    finally:
        await db.close()

async def get_daily_stats(days: int = 7):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT date, total_downloads FROM stats ORDER BY date DESC LIMIT ?", (days,)
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()



# ─── Stars payments tracking ────────────────────────────────
async def record_payment(user_id: int, username: str = None, first_name: str = None,
                         payload: str = None, item_type: str = None, quality: str = None,
                         stars_amount: int = 0, currency: str = "XTR",
                         telegram_payment_charge_id: str = None,
                         provider_payment_charge_id: str = None) -> int:
    """Store a successful Telegram Stars payment for admin audit/history."""
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO payments
               (user_id, username, first_name, payload, item_type, quality,
                stars_amount, currency, telegram_payment_charge_id,
                provider_payment_charge_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username, first_name, payload, item_type, quality,
             stars_amount, currency, telegram_payment_charge_id,
             provider_payment_charge_id),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def get_recent_payments(limit: int = 20) -> list[dict]:
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM payments ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_user_group_count(user_id: int) -> int:
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT COUNT(*) FROM group_chats WHERE added_by = ? AND is_active = 1",
            (user_id,),
        )
        return int(rows[0][0]) if rows else 0
    finally:
        await db.close()

# ─── Bot settings (admin feature toggles) ───────────────────
async def get_setting(key: str, default: str = "1") -> str:
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT value FROM bot_settings WHERE `key` = ?", (key,))
        return rows[0][0] if rows else default
    finally:
        await db.close()

async def get_all_settings() -> dict:
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT `key`, value FROM bot_settings")
        return {r[0]: r[1] for r in rows}
    finally:
        await db.close()

async def set_setting(key: str, value: str):
    db = await get_db()
    try:
        if config.DB_TYPE == "mysql":
            await db.execute(
                "INSERT INTO bot_settings (`key`, value) VALUES (?, ?) "
                "ON DUPLICATE KEY UPDATE value = VALUES(value)",
                (key, value),
            )
        else:
            await db.execute(
                "INSERT INTO bot_settings (`key`, value) VALUES (?, ?) "
                "ON CONFLICT(`key`) DO UPDATE SET value = ?",
                (key, value, value)
            )
        await db.commit()
    finally:
        await db.close()

async def toggle_setting(key: str) -> str:
    current = await get_setting(key)
    new = "0" if current == "1" else "1"
    await set_setting(key, new)
    return new

# ─── User language ──────────────────────────────────────────
async def get_user_language(user_id: int) -> str:
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT language FROM users WHERE user_id = ?", (user_id,))
        if rows and rows[0][0]:
            return rows[0][0]
        return "en"
    finally:
        await db.close()

async def set_user_language(user_id: int, lang: str):
    db = await get_db()
    try:
        await db.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
        await db.commit()
    finally:
        await db.close()

# ─── Per-user settings (language / tags / source channel / mode) ────
# Columns that the user can toggle from their personal ⚙️ Settings menu.
USER_FLAG_COLUMNS = {"show_tags", "show_source_channel", "tiktok_watermark"}
VALID_DOWNLOAD_MODES = ("ask", "video", "audio")
VALID_DESCRIPTION_MODES = ("off", "separate", "with", "quote", "country")
VALID_CAPTION_MODES = ("src_via", "src", "src_plus", "author", "off")
VALID_GALLERY_MODES = ("photos", "video")
VALID_AUDIO_MODES = ("off", "separate")


_DESC_PLATFORMS = ("instagram", "tiktok", "threads", "youtube")


async def get_user_settings(user_id: int) -> dict:
    """Return this user's personal preferences with safe defaults."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT language, show_tags, show_source_channel, download_mode, "
            "tiktok_watermark, description_mode, caption_mode, gallery_mode, audio_mode, "
            "desc_mode_instagram, desc_mode_tiktok, desc_mode_threads, desc_mode_youtube "
            "FROM users WHERE user_id = ?",
            (user_id,),
        )
        defaults = {
            "language": "en",
            "show_tags": False,
            "show_source_channel": False,
            "download_mode": "ask",
            "tiktok_watermark": False,
            "description_mode": "with",
            "caption_mode": "src_via",
            "gallery_mode": "photos",
            "audio_mode": "off",
            "desc_mode_instagram": "default",
            "desc_mode_tiktok": "default",
            "desc_mode_threads": "default",
            "desc_mode_youtube": "default",
        }
        if not rows:
            return defaults
        r = dict(rows[0])
        mode = r.get("download_mode") or "ask"
        if mode not in VALID_DOWNLOAD_MODES:
            mode = "ask"
        desc_mode = r.get("description_mode") or "off"
        if desc_mode not in VALID_DESCRIPTION_MODES:
            desc_mode = "off"
        cap_mode = r.get("caption_mode") or "src_via"
        if cap_mode not in VALID_CAPTION_MODES:
            cap_mode = "src_via"
        gal_mode = r.get("gallery_mode") or "photos"
        if gal_mode not in VALID_GALLERY_MODES:
            gal_mode = "photos"
        aud_mode = r.get("audio_mode") or "off"
        if aud_mode not in VALID_AUDIO_MODES:
            aud_mode = "off"
        result = {
            "language": r.get("language") or "en",
            "show_tags": bool(r.get("show_tags")),
            "show_source_channel": bool(r.get("show_source_channel")),
            "download_mode": mode,
            "tiktok_watermark": bool(r.get("tiktok_watermark")),
            "description_mode": desc_mode,
            "caption_mode": cap_mode,
            "gallery_mode": gal_mode,
            "audio_mode": aud_mode,
        }
        # Per-platform description modes ("default" = inherit global setting)
        for plat in _DESC_PLATFORMS:
            col = f"desc_mode_{plat}"
            val = r.get(col) or "default"
            if val != "default" and val not in VALID_DESCRIPTION_MODES:
                val = "default"
            result[col] = val
        return result
    finally:
        await db.close()


async def toggle_user_flag(user_id: int, field: str) -> bool:
    """Flip a boolean per-user preference column. Returns the new value."""
    if field not in USER_FLAG_COLUMNS:
        raise ValueError(f"Unknown user flag: {field}")
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            f"SELECT {field} FROM users WHERE user_id = ?", (user_id,)
        )
        current = bool(rows[0][0]) if rows else False
        new = 0 if current else 1
        await db.execute(
            f"UPDATE users SET {field} = ? WHERE user_id = ?", (new, user_id)
        )
        await db.commit()
        return bool(new)
    finally:
        await db.close()


async def get_user_download_mode(user_id: int) -> str:
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT download_mode FROM users WHERE user_id = ?", (user_id,)
        )
        mode = rows[0][0] if rows and rows[0][0] else "ask"
        return mode if mode in VALID_DOWNLOAD_MODES else "ask"
    finally:
        await db.close()


async def set_user_download_mode(user_id: int, mode: str):
    if mode not in VALID_DOWNLOAD_MODES:
        mode = "ask"
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET download_mode = ? WHERE user_id = ?", (mode, user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def set_user_description_mode(user_id: int, mode: str):
    """Set how the post description/text is delivered (see VALID_DESCRIPTION_MODES)."""
    if mode not in VALID_DESCRIPTION_MODES:
        mode = "off"
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET description_mode = ? WHERE user_id = ?", (mode, user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def set_user_platform_desc_mode(user_id: int, platform: str, mode: str):
    """Set per-platform description mode (instagram / tiktok / threads / youtube)."""
    if platform not in _DESC_PLATFORMS:
        return
    if mode != "default" and mode not in VALID_DESCRIPTION_MODES:
        mode = "default"
    col = f"desc_mode_{platform}"
    db = await get_db()
    try:
        await db.execute(
            f"UPDATE users SET {col} = ? WHERE user_id = ?", (mode, user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def set_user_caption_mode(user_id: int, mode: str):
    """Set what the credit line under the content shows (see VALID_CAPTION_MODES)."""
    if mode not in VALID_CAPTION_MODES:
        mode = "src_via"
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET caption_mode = ? WHERE user_id = ?", (mode, user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def set_user_gallery_mode(user_id: int, mode: str):
    """Set how photo carousels are delivered (see VALID_GALLERY_MODES)."""
    if mode not in VALID_GALLERY_MODES:
        mode = "photos"
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET gallery_mode = ? WHERE user_id = ?", (mode, user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def set_user_audio_mode(user_id: int, mode: str):
    """Set whether a photo post's audio is also sent separately (see VALID_AUDIO_MODES)."""
    if mode not in VALID_AUDIO_MODES:
        mode = "off"
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET audio_mode = ? WHERE user_id = ?", (mode, user_id)
        )
        await db.commit()
    finally:
        await db.close()


# ─── Per-group / per-chat settings ──────────────────────────
# Boolean columns an admin can toggle from the per-group settings panel.
GROUP_FLAG_COLUMNS = {"show_tags", "show_source_channel", "delete_user_url"}


async def ensure_group_chat(chat_id: int, title: str = None, chat_type: str = None,
                            added_by: int = None, language: str = None) -> None:
    """Register (or refresh) a group/channel the bot lives in.

    New rows inherit the current global `group_download_mode` so behaviour is
    preserved for chats created before this feature. Existing rows only get
    their title / type / added_by / is_active refreshed (settings untouched).
    """
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT chat_id FROM group_chats WHERE chat_id = ?", (chat_id,)
        )
        if rows:
            # Refresh metadata, mark active again. Keep added_by if we already
            # have one (don't overwrite the original adder with NULL).
            if added_by is not None:
                await db.execute(
                    "UPDATE group_chats SET title = COALESCE(?, title), "
                    "chat_type = COALESCE(?, chat_type), language = COALESCE(?, language), "
                    "added_by = ?, is_active = 1 WHERE chat_id = ?",
                    (title, chat_type, language, added_by, chat_id),
                )
            else:
                await db.execute(
                    "UPDATE group_chats SET title = COALESCE(?, title), "
                    "chat_type = COALESCE(?, chat_type), language = COALESCE(?, language), "
                    "is_active = 1 WHERE chat_id = ?",
                    (title, chat_type, language, chat_id),
                )
        else:
            default_mode = "ask"
            srow = await db.execute_fetchall(
                "SELECT value FROM bot_settings WHERE `key` = 'group_download_mode'"
            )
            if srow and srow[0][0] in VALID_DOWNLOAD_MODES:
                default_mode = srow[0][0]
            await db.execute(
                "INSERT INTO group_chats (chat_id, title, chat_type, language, added_by, "
                "download_mode, is_active) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (chat_id, title, chat_type, language or "en", added_by, default_mode),
            )
        await db.commit()
    finally:
        await db.close()


async def set_group_inactive(chat_id: int) -> None:
    """Mark a group inactive (bot was removed / kicked). Settings are kept."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE group_chats SET is_active = 0 WHERE chat_id = ?", (chat_id,)
        )
        await db.commit()
    finally:
        await db.close()


def _group_row_to_settings(r: dict) -> dict:
    mode = r.get("download_mode") or "ask"
    if mode not in VALID_DOWNLOAD_MODES:
        mode = "ask"
    cap_mode = r.get("caption_mode") or "src_via"
    if cap_mode not in VALID_CAPTION_MODES:
        cap_mode = "src_via"
    return {
        "chat_id": r["chat_id"],
        "title": r.get("title") or str(r["chat_id"]),
        "chat_type": r.get("chat_type"),
        "language": r.get("language") or "en",
        "added_by": r.get("added_by"),
        "show_tags": bool(r.get("show_tags")),
        "show_source_channel": bool(r.get("show_source_channel")),
        "download_mode": mode,
        "delete_user_url": bool(r.get("delete_user_url")),
        "caption_mode": cap_mode,
        "description_mode": (r.get("description_mode") if r.get("description_mode") in VALID_DESCRIPTION_MODES else "off"),
        "is_active": bool(r.get("is_active")),
    }


async def get_group_settings(chat_id: int) -> dict | None:
    """Return a group's settings dict, or None if the chat is unknown."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM group_chats WHERE chat_id = ?", (chat_id,)
        )
        if not rows:
            return None
        return _group_row_to_settings(dict(rows[0]))
    finally:
        await db.close()


async def list_user_groups(user_id: int) -> list[dict]:
    """Active groups/chats this user added the bot to."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM group_chats WHERE added_by = ? AND is_active = 1 "
            "ORDER BY created_at DESC",
            (user_id,),
        )
        return [_group_row_to_settings(dict(r)) for r in rows]
    finally:
        await db.close()


async def list_active_groups(limit: int = 200) -> list[dict]:
    """All active groups/chats the bot currently knows about (most recent first)."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM group_chats WHERE is_active = 1 "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [_group_row_to_settings(dict(r)) for r in rows]
    finally:
        await db.close()


async def claim_group(chat_id: int, user_id: int) -> None:
    """Attribute a group with unknown adder to a confirmed admin, so it lists
    instantly next time. Only fills added_by when it is currently NULL."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE group_chats SET added_by = ? WHERE chat_id = ? AND added_by IS NULL",
            (user_id, chat_id),
        )
        await db.commit()
    finally:
        await db.close()


async def toggle_group_flag(chat_id: int, field: str) -> bool:
    """Flip a boolean per-group setting. Returns the new value."""
    if field not in GROUP_FLAG_COLUMNS:
        raise ValueError(f"Unknown group flag: {field}")
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            f"SELECT {field} FROM group_chats WHERE chat_id = ?", (chat_id,)
        )
        if not rows:
            raise ValueError("Unknown group")
        new = 0 if bool(rows[0][0]) else 1
        await db.execute(
            f"UPDATE group_chats SET {field} = ? WHERE chat_id = ?", (new, chat_id)
        )
        await db.commit()
        return bool(new)
    finally:
        await db.close()


async def set_group_download_mode(chat_id: int, mode: str) -> None:
    if mode not in VALID_DOWNLOAD_MODES:
        mode = "ask"
    db = await get_db()
    try:
        await db.execute(
            "UPDATE group_chats SET download_mode = ? WHERE chat_id = ?", (mode, chat_id)
        )
        await db.commit()
    finally:
        await db.close()


async def set_group_language(chat_id: int, language: str) -> None:
    """Set bot UI/message language for a specific group/chat."""
    if not language:
        language = "en"
    db = await get_db()
    try:
        await db.execute(
            "UPDATE group_chats SET language = ? WHERE chat_id = ?", (language, chat_id)
        )
        await db.commit()
    finally:
        await db.close()


async def set_group_description_mode(chat_id: int, mode: str) -> None:
    """Set how source description/text is delivered in a group/chat."""
    if mode not in VALID_DESCRIPTION_MODES:
        mode = "off"
    db = await get_db()
    try:
        await db.execute(
            "UPDATE group_chats SET description_mode = ? WHERE chat_id = ?", (mode, chat_id)
        )
        await db.commit()
    finally:
        await db.close()


async def set_group_caption_mode(chat_id: int, mode: str) -> None:
    """Set what the group/chat credit line shows (see VALID_CAPTION_MODES)."""
    if mode not in VALID_CAPTION_MODES:
        mode = "src_via"
    db = await get_db()
    try:
        await db.execute(
            "UPDATE group_chats SET caption_mode = ? WHERE chat_id = ?", (mode, chat_id)
        )
        await db.commit()
    finally:
        await db.close()
