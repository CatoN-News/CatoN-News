"""
CatoN News (CNN) — 数据模型（dataclass 版）
纯数据容器，数据库操作在 database.py 中通过原始 SQL 完成。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Video:
    """视频原始数据。"""
    bvid: str
    title: str
    author: str
    mid: int
    pubdate: int
    week: str
    view: int = 0
    like: int = 0
    coin: int = 0
    favorite: int = 0
    share: int = 0
    reply: int = 0
    duration: int = 0
    tags: Optional[str] = None
    is_vocaloid: bool = False
    vocaloid_score: int = 0
    base_score: float = 0.0
    id: Optional[int] = None
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "Video":
        """从 sqlite3.Row 或 dict 构造。"""
        return cls(
            id=row.get("id"),
            bvid=row["bvid"],
            title=row["title"],
            author=row["author"],
            mid=row["mid"],
            pubdate=row["pubdate"],
            view=row.get("view", 0),
            like=row.get("like", 0),
            coin=row.get("coin", 0),
            favorite=row.get("favorite", 0),
            share=row.get("share", 0),
            reply=row.get("reply", 0),
            duration=row.get("duration", 0),
            tags=row.get("tags"),
            is_vocaloid=bool(row.get("is_vocaloid", False)),
            vocaloid_score=row.get("vocaloid_score", 0),
            base_score=row.get("base_score", 0.0),
            week=row["week"],
            created_at=row.get("created_at"),
        )


@dataclass
class Ranking:
    """排名结果。"""
    week: str
    rank: int
    bvid: str
    title: str
    author: str
    author_type: str = "unauthorized"
    view: int = 0
    coin: int = 0
    favorite: int = 0
    base_score: float = 0.0
    time_factor: float = 1.0
    author_weight: float = 1.0
    final_score: float = 0.0
    hours_old: float = 0.0
    id: Optional[int] = None
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "Ranking":
        """从 sqlite3.Row 或 dict 构造。"""
        return cls(
            id=row.get("id"),
            week=row["week"],
            rank=row["rank"],
            bvid=row["bvid"],
            title=row["title"],
            author=row["author"],
            author_type=row.get("author_type", "unauthorized"),
            view=row.get("view", 0),
            coin=row.get("coin", 0),
            favorite=row.get("favorite", 0),
            base_score=row.get("base_score", 0.0),
            time_factor=row.get("time_factor", 1.0),
            author_weight=row.get("author_weight", 1.0),
            final_score=row.get("final_score", 0.0),
            hours_old=row.get("hours_old", 0.0),
            created_at=row.get("created_at"),
        )


@dataclass
class Admin:
    """管理员账号。"""
    username: str
    password_hash: str
    id: Optional[int] = None
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "Admin":
        return cls(
            id=row.get("id"),
            username=row["username"],
            password_hash=row["password_hash"],
            created_at=row.get("created_at"),
        )
