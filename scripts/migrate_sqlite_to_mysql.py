"""Migrate existing SQLite data/smdown.db to MySQL.

Run from the project root after filling .env MySQL settings:
    python scripts/migrate_sqlite_to_mysql.py

It copies known bot tables and uses upsert, so it is safe to run again.
"""
import asyncio
import os
import sqlite3
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import aiomysql

TABLES = ["users", "downloads", "stats", "bot_settings", "payments", "group_chats"]


def env(name, default=""):
    return os.getenv(name, default)


async def mysql_connect():
    return await aiomysql.connect(
        host=env("MYSQL_HOST", "127.0.0.1"),
        port=int(env("MYSQL_PORT", "3306")),
        user=env("MYSQL_USER", "smdownbot"),
        password=env("MYSQL_PASSWORD", ""),
        db=env("MYSQL_DATABASE", "smdownbot"),
        charset=env("MYSQL_CHARSET", "utf8mb4"),
        autocommit=False,
    )


def sqlite_rows(sqlite_path: Path, table: str):
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            return []
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
    finally:
        conn.close()


async def mysql_columns(conn, table: str) -> set[str]:
    async with conn.cursor() as cur:
        await cur.execute(f"SHOW COLUMNS FROM `{table}`")
        rows = await cur.fetchall()
    return {r[0] for r in rows}


async def upsert_rows(conn, table: str, rows: list[dict]):
    if not rows:
        print(f"{table}: 0 rows")
        return
    cols_allowed = await mysql_columns(conn, table)
    cols = [c for c in rows[0].keys() if c in cols_allowed]
    if not cols:
        print(f"{table}: no matching columns")
        return

    col_sql = ", ".join(f"`{c}`" for c in cols)
    placeholders = ", ".join(["%s"] * len(cols))
    update_sql = ", ".join(f"`{c}`=VALUES(`{c}`)" for c in cols)
    sql = f"INSERT INTO `{table}` ({col_sql}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {update_sql}"
    values = [tuple(r.get(c) for c in cols) for r in rows]

    async with conn.cursor() as cur:
        await cur.executemany(sql, values)
    print(f"{table}: copied {len(rows)} rows")


async def main():
    sqlite_path = Path(env("DB_PATH", "data/smdown.db"))
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite DB not found: {sqlite_path}")

    print("SQLite:", sqlite_path)
    print("MySQL:", f"{env('MYSQL_USER', 'smdownbot')}@{env('MYSQL_HOST', '127.0.0.1')}:{env('MYSQL_PORT', '3306')}/{env('MYSQL_DATABASE', 'smdownbot')}")
    conn = await mysql_connect()
    try:
        for table in TABLES:
            await upsert_rows(conn, table, sqlite_rows(sqlite_path, table))
        await conn.commit()
        print("Done.")
    except Exception:
        await conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
