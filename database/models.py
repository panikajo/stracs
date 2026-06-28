import aiosqlite

try:
    import aiomysql
except ImportError:  # MySQL is optional unless DB_TYPE=mysql
    aiomysql = None

from config import config

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

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    first_name TEXT,
    payload TEXT,
    item_type TEXT,
    quality TEXT,
    stars_amount INTEGER,
    currency TEXT DEFAULT 'XTR',
    telegram_payment_charge_id TEXT,
    provider_payment_charge_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS group_chats (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    chat_type TEXT,
    language TEXT DEFAULT 'en',
    added_by INTEGER,
    show_tags INTEGER DEFAULT 0,
    show_source_channel INTEGER DEFAULT 0,
    download_mode TEXT DEFAULT 'ask',
    delete_user_url INTEGER DEFAULT 0,
    caption_mode TEXT DEFAULT 'src_via',
    description_mode TEXT DEFAULT 'off',
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

MYSQL_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username VARCHAR(255),
        first_name VARCHAR(255),
        daily_limit INT DEFAULT 20,
        downloads_today INT DEFAULT 0,
        last_reset VARCHAR(32),
        extra_downloads INT DEFAULT 0,
        is_banned TINYINT DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS downloads (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT,
        url TEXT,
        platform VARCHAR(64),
        title TEXT,
        file_size BIGINT,
        status VARCHAR(32) DEFAULT 'pending',
        chat_id BIGINT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_downloads_user (user_id),
        INDEX idx_downloads_chat (chat_id, created_at)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS stats (
        date VARCHAR(32) PRIMARY KEY,
        total_downloads INT DEFAULT 0,
        total_users INT DEFAULT 0,
        by_platform TEXT
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS bot_settings (
        `key` VARCHAR(191) PRIMARY KEY,
        value TEXT
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS payments (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT,
        username VARCHAR(255),
        first_name VARCHAR(255),
        payload TEXT,
        item_type VARCHAR(64),
        quality VARCHAR(64),
        stars_amount INT,
        currency VARCHAR(16) DEFAULT 'XTR',
        telegram_payment_charge_id VARCHAR(255),
        provider_payment_charge_id VARCHAR(255),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_payments_user (user_id),
        INDEX idx_payments_created (created_at)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS group_chats (
        chat_id BIGINT PRIMARY KEY,
        title VARCHAR(255),
        chat_type VARCHAR(64),
        language VARCHAR(16) DEFAULT 'en',
        added_by BIGINT,
        show_tags TINYINT DEFAULT 0,
        show_source_channel TINYINT DEFAULT 0,
        download_mode VARCHAR(32) DEFAULT 'ask',
        delete_user_url TINYINT DEFAULT 0,
        caption_mode VARCHAR(32) DEFAULT 'src_via',
        description_mode VARCHAR(32) DEFAULT 'off',
        is_active TINYINT DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_group_added_by (added_by),
        INDEX idx_group_active (is_active)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""",
]

# Settings that can be toggled from the admin panel. Default: all enabled ("1").
DEFAULT_SETTINGS = {
    "feature_youtube": "1",
    "feature_instagram": "1",
    "feature_tiktok": "1",
    "feature_threads": "1",
    "feature_stars": "1",
    "feature_bulk_stories": "1",
    "feature_language_select": "1",
    "feature_user_settings": "1",
    "feature_group_buttons": "0",
    "feature_show_tags": "0",
    "feature_show_source_channel": "0",
    "group_download_mode": "ask",
}

USER_MIGRATIONS = {
    "language": "TEXT DEFAULT 'en'",
    "show_tags": "INTEGER DEFAULT 0",
    "show_source_channel": "INTEGER DEFAULT 0",
    "download_mode": "TEXT DEFAULT 'ask'",
    "tiktok_watermark": "INTEGER DEFAULT 0",
    "description_mode": "TEXT DEFAULT 'off'",
    "caption_mode": "TEXT DEFAULT 'src_via'",
    "gallery_mode": "TEXT DEFAULT 'photos'",
    "audio_mode": "TEXT DEFAULT 'off'",
}

DOWNLOAD_MIGRATIONS = {
    "chat_id": "INTEGER",
}

GROUP_MIGRATIONS = {
    "language": "TEXT DEFAULT 'en'",
    "caption_mode": "TEXT DEFAULT 'src_via'",
    "description_mode": "TEXT DEFAULT 'off'",
}

MYSQL_USER_MIGRATIONS = {
    "language": "VARCHAR(16) DEFAULT 'en'",
    "show_tags": "TINYINT DEFAULT 0",
    "show_source_channel": "TINYINT DEFAULT 0",
    "download_mode": "VARCHAR(32) DEFAULT 'ask'",
    "tiktok_watermark": "TINYINT DEFAULT 0",
    "description_mode": "VARCHAR(32) DEFAULT 'off'",
    "caption_mode": "VARCHAR(32) DEFAULT 'src_via'",
    "gallery_mode": "VARCHAR(32) DEFAULT 'photos'",
    "audio_mode": "VARCHAR(32) DEFAULT 'off'",
}
MYSQL_DOWNLOAD_MIGRATIONS = {"chat_id": "BIGINT NULL"}
MYSQL_GROUP_MIGRATIONS = {
    "language": "VARCHAR(16) DEFAULT 'en'",
    "caption_mode": "VARCHAR(32) DEFAULT 'src_via'",
    "description_mode": "VARCHAR(32) DEFAULT 'off'",
}


async def _mysql_connect():
    if aiomysql is None:
        raise RuntimeError("DB_TYPE=mysql requires: pip install aiomysql")
    return await aiomysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        db=config.MYSQL_DATABASE,
        charset=config.MYSQL_CHARSET,
        autocommit=False,
    )


async def _mysql_columns(db, table: str) -> set[str]:
    async with db.cursor() as cur:
        await cur.execute(f"SHOW COLUMNS FROM `{table}`")
        rows = await cur.fetchall()
    return {r[0] for r in rows}


async def _mysql_add_missing_columns(db, table: str, migrations: dict[str, str]):
    cols = await _mysql_columns(db, table)
    async with db.cursor() as cur:
        for name, ddl in migrations.items():
            if name not in cols:
                await cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}")


async def _init_mysql_db():
    db = await _mysql_connect()
    try:
        async with db.cursor() as cur:
            for stmt in MYSQL_SCHEMA:
                await cur.execute(stmt)
        await _mysql_add_missing_columns(db, "users", MYSQL_USER_MIGRATIONS)
        await _mysql_add_missing_columns(db, "downloads", MYSQL_DOWNLOAD_MIGRATIONS)
        await _mysql_add_missing_columns(db, "group_chats", MYSQL_GROUP_MIGRATIONS)
        async with db.cursor() as cur:
            for k, v in DEFAULT_SETTINGS.items():
                await cur.execute(
                    "INSERT IGNORE INTO bot_settings (`key`, value) VALUES (%s, %s)",
                    (k, v),
                )
        await db.commit()
    finally:
        db.close()


async def _init_sqlite_db(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(DB_SCHEMA)
        cur = await db.execute("PRAGMA table_info(users)")
        cols = [r[1] for r in await cur.fetchall()]
        for name, ddl in USER_MIGRATIONS.items():
            if name not in cols:
                await db.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")

        cur = await db.execute("PRAGMA table_info(downloads)")
        dl_cols = [r[1] for r in await cur.fetchall()]
        for name, ddl in DOWNLOAD_MIGRATIONS.items():
            if name not in dl_cols:
                await db.execute(f"ALTER TABLE downloads ADD COLUMN {name} {ddl}")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_downloads_chat ON downloads(chat_id, created_at)"
        )

        cur = await db.execute("PRAGMA table_info(group_chats)")
        group_cols = [r[1] for r in await cur.fetchall()]
        for name, ddl in GROUP_MIGRATIONS.items():
            if name not in group_cols:
                await db.execute(f"ALTER TABLE group_chats ADD COLUMN {name} {ddl}")

        for k, v in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)", (k, v)
            )
        await db.commit()


async def init_db(db_path: str):
    if config.DB_TYPE == "mysql":
        await _init_mysql_db()
    else:
        await _init_sqlite_db(db_path)
