"""
CatoN News (CNN) — 数据库连接与会话管理
使用 Python 标准库 sqlite3，零编译依赖。
"""

import logging
import sqlite3
from contextlib import contextmanager
from typing import Generator

from config import DATABASE_PATH

logger = logging.getLogger(__name__)


def get_conn() -> sqlite3.Connection:
    """获取数据库连接（WAL 模式，row_factory 方便访问）。"""
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """创建所有表（如果不存在）。"""
    conn = get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bvid TEXT NOT NULL,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                mid INTEGER NOT NULL,
                pubdate INTEGER NOT NULL,
                view INTEGER DEFAULT 0,
                "like" INTEGER DEFAULT 0,
                coin INTEGER DEFAULT 0,
                favorite INTEGER DEFAULT 0,
                share INTEGER DEFAULT 0,
                reply INTEGER DEFAULT 0,
                duration INTEGER DEFAULT 0,
                tags TEXT,
                is_vocaloid INTEGER DEFAULT 0,
                vocaloid_score INTEGER DEFAULT 0,
                description TEXT DEFAULT '',
                base_score REAL DEFAULT 0,
                week TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bvid, week)
            );

            CREATE TABLE IF NOT EXISTS rankings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week TEXT NOT NULL,
                rank INTEGER NOT NULL,
                bvid TEXT NOT NULL,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                author_type TEXT DEFAULT 'unauthorized',
                view INTEGER DEFAULT 0,
                coin INTEGER DEFAULT 0,
                favorite INTEGER DEFAULT 0,
                base_score REAL DEFAULT 0,
                time_factor REAL DEFAULT 1.0,
                author_weight REAL DEFAULT 1.0,
                final_score REAL DEFAULT 0,
                hours_old REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(week, rank)
            );

            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_videos_bvid ON videos(bvid);
            CREATE INDEX IF NOT EXISTS idx_videos_week ON videos(week);
            CREATE INDEX IF NOT EXISTS idx_rankings_week ON rankings(week);
            CREATE INDEX IF NOT EXISTS idx_rankings_bvid ON rankings(bvid);
        """)
        # 兼容旧数据库：添加 description 列（如果不存在）
        try:
            conn.execute("ALTER TABLE videos ADD COLUMN description TEXT DEFAULT ''")
        except Exception:
            pass  # 列已存在

        conn.commit()
        logger.info("数据库初始化完成: %s", DATABASE_PATH)
    finally:
        conn.close()


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """获取数据库连接上下文管理器。

    用法:
        with get_db() as db:
            rows = db.execute("SELECT * FROM videos").fetchall()
    """
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("数据库操作异常，已回滚")
        raise
    finally:
        conn.close()
