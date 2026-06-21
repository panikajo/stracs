import aiosqlite
from datetime import datetime, date

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    daily_limit INTEGER DEFAULT 20,
    downloads_today INTEGER DEFAULT 0,
    last_reset TEXT,
    extra_downloads INTEGER DEFAULT 0,
    is_banned INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    url TEXT,
    platform TEXT,
    title TEXT,
    file_size INTEGER,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS stats (
    date TEXT PRIMARY KEY,
    total_downloads INTEGER DEFAULT 0,
    total_users INTEGER DEFAULT 0,
    by_platform TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS group_chats (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    chat_type TEXT,
    added_by INTEGER,
    show_tags INTEGER DEFAULT 0,
    show_source_channel INTEGER DEFAULT 0,
    download_mode TEXT DEFAULT 'ask',
    delete_user_url INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# Settings that can be toggled from the admin panel. Default: all enabled ("1").
DEFAULT_SETTINGS = {
    "feature_youtube": "1",
    "feature_instagram": "1",
    "feature_tiktok": "1",
    "feature_stars": "1",
    "feature_bulk_stories": "1",
    "feature_language_select": "1",
    # Per-user Settings menu (⚙️) — ON by default
    "feature_user_settings": "1",
    # Reply-keyboard buttons inside groups/channels — OFF by default
    "feature_group_buttons": "0",
    # Show source hashtags in the video caption — OFF by default.
    # NOTE: this is now a GLOBAL master "force-on for everyone" switch.
    # When OFF (default) each user decides via their personal Settings menu.
    "feature_show_tags": "0",
    # Show source channel/author login in the caption — OFF by default.
    # Same semantics as feature_show_tags (global force-on for everyone).
    "feature_show_source_channel": "0",
    # In groups/channels: what to do with a link.
    #   "ask"   — show the quality/format buttons (default)
    #   "video" — auto-download video, no buttons
    #   "audio" — auto-download audio, no buttons
    "group_download_mode": "ask",
}


async def init_db(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(DB_SCHEMA)
        # Migration: add per-user columns to `users` if missing.
        cur = await db.execute("PRAGMA table_info(users)")
        cols = [r[1] for r in await cur.fetchall()]
        if "language" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'en'")
        # Per-user preference: show source hashtags in the caption (0/1)
        if "show_tags" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN show_tags INTEGER DEFAULT 0")
        # Per-user preference: show source channel/@login in the caption (0/1)
        if "show_source_channel" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN show_source_channel INTEGER DEFAULT 0")
        # Per-user default download mode in private chats:
        #   "ask"   — show quality/format buttons (default)
        #   "video" — auto-download video, no buttons
        #   "audio" — auto-download audio, no buttons
        if "download_mode" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN download_mode TEXT DEFAULT 'ask'")
        # Per-user preference: download TikTok WITH the platform watermark (0/1).
        # Default 0 → no-watermark (current behaviour).
        if "tiktok_watermark" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN tiktok_watermark INTEGER DEFAULT 0")
        # Per-user preference: how to deliver the post description / text.
        #   'off'      — don't show it (default)
        #   'separate' — send it as a separate message under the content
        #   'with'     — append it to the media caption
        #   'quote'    — append it to the caption as a <blockquote>
        #   'country'  — show the upload country/geo (when the platform exposes it)
        if "description_mode" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN description_mode TEXT DEFAULT 'off'")
        # Per-user preference: what the credit line under the content shows.
        #   'src_via'  — Source + Via (author)  [default, current behaviour]
        #   'src'      — Source only
        #   'src_plus' — Source (reserved for a future /custom_caption suffix)
        #   'author'   — Author only
        #   'off'      — no credit line
        if "caption_mode" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN caption_mode TEXT DEFAULT 'src_via'")
        # Per-user preference: how to deliver a photo carousel / slideshow post.
        #   'photos' — send the images as an album (default)
        #   'video'  — render the images into a slideshow video with the post's music
        if "gallery_mode" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN gallery_mode TEXT DEFAULT 'photos'")
        # Per-user preference: what to do with a photo post's audio track.
        #   'off'      — don't send the audio separately (default)
        #   'separate' — also send the audio as a separate .mp3 file
        if "audio_mode" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN audio_mode TEXT DEFAULT 'off'")
        # Migration: add chat_id to `downloads` so we can show per-chat/per-group
        # download statistics (grouped by platform). NULL for old rows.
        cur = await db.execute("PRAGMA table_info(downloads)")
        dl_cols = [r[1] for r in await cur.fetchall()]
        if "chat_id" not in dl_cols:
            await db.execute("ALTER TABLE downloads ADD COLUMN chat_id INTEGER")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_downloads_chat ON downloads(chat_id, created_at)"
        )
        # Seed default settings
        for k, v in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)", (k, v)
            )
        await db.commit()
