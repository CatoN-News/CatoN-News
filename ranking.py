"""
CatoN News (CNN) — 排名计算模块
基础分、时间因子、作者权重、最终得分。
"""

import logging
import math
from typing import Optional

from config import (
    AUTHOR_WEIGHT,
    CANDIDATE_COUNT,
    CYCLE_HOURS,
    FINAL_RANK_COUNT,
    TIME_ALPHA,
    W_COIN,
    W_FAVORITE,
    W_LIKE,
    W_VIEW,
)
from database import get_db

logger = logging.getLogger(__name__)


def calculate_base_score(
    view: int = 0,
    favorite: int = 0,
    like: int = 0,
    coin: int = 0,
) -> float:
    """计算基础分。

    基础分 = 播放×1 + 收藏×25 + 点赞×2 + 投币×8
    """
    return (
        view * W_VIEW
        + favorite * W_FAVORITE
        + like * W_LIKE
        + coin * W_COIN
    )


def calculate_time_factor(
    pubdate: int,
    deadline_ts: int,
    alpha: float = TIME_ALPHA,
) -> float:
    """计算时间因子（后发补偿）。

    Args:
        pubdate: 投稿时间戳（Unix）
        deadline_ts: 统计截止时间戳（Unix）
        alpha: 衰减系数

    Returns:
        时间因子，新投稿高于 1.0，满七天的投稿为 1.0
    """
    hours_old = (deadline_ts - pubdate) / 3600.0
    hours_old = max(0, hours_old)  # 防止负数
    factor = math.exp(alpha * (1.0 - hours_old / CYCLE_HOURS))
    return round(factor, 4)


def calculate_hours_old(pubdate: int, deadline_ts: int) -> float:
    """计算视频从投稿到统计截止的已有时长（小时）。"""
    return (deadline_ts - pubdate) / 3600.0


def calculate_final_score(
    base_score: float,
    time_factor: float,
    author_weight: float = 1.0,
) -> float:
    """计算最终得分。

    最终得分 = 基础分 × 时间因子 × 作者权重
    """
    return round(base_score * time_factor * author_weight, 2)


def generate_candidates(
    week: str,
    deadline_ts: Optional[int] = None,
) -> list[dict]:
    """获取某周的前30名候选（按基础分排序），计算时间因子和最终得分。

    Args:
        week: 期数，如 "2026W30"
        deadline_ts: 统计截止时间戳，None 时自动取周期结束时间

    Returns:
        候选列表，每项含所有得分字段
    """
    with get_db() as db:
        rows = db.execute("""
            SELECT *
            FROM videos
            WHERE week = ? AND is_vocaloid = 1
            AND view >= 100 AND coin >= 20
            ORDER BY base_score DESC
            LIMIT ?
        """, (week, CANDIDATE_COUNT)).fetchall()

    if not rows:
        logger.warning("期数 %s 无符合条件的视频", week)
        return []

    # 自动计算截止时间（如果未提供）
    if deadline_ts is None:
        # 从该期第一条视频的 pubdate 推断周范围
        pubdates = [r["pubdate"] for r in rows]
        latest_pubdate = max(pubdates)
        # 截止时间是该周期的周二 12:00
        deadline_ts = latest_pubdate + CYCLE_HOURS * 3600

    candidates = []
    for i, row in enumerate(rows):
        row_dict = dict(row)
        base_score = row_dict.get("base_score", 0.0) or calculate_base_score(
            view=row_dict.get("view", 0),
            favorite=row_dict.get("favorite", 0),
            like=row_dict.get("like", 0),
            coin=row_dict.get("coin", 0),
        )
        hours_old = calculate_hours_old(row_dict["pubdate"], deadline_ts)
        time_factor = calculate_time_factor(row_dict["pubdate"], deadline_ts)
        author_type = row_dict.get("author_type", "unauthorized") or "unauthorized"
        author_weight = AUTHOR_WEIGHT.get(author_type, 1.0)
        final_score = calculate_final_score(base_score, time_factor, author_weight)

        row_dict["base_score"] = base_score
        row_dict["hours_old"] = round(hours_old, 1)
        row_dict["time_factor"] = time_factor
        row_dict["author_type"] = author_type
        row_dict["author_weight"] = author_weight
        row_dict["final_score"] = final_score
        row_dict["candidate_rank"] = i + 1

        candidates.append(row_dict)

    return candidates


def generate_final_rankings(
    week: str,
    candidates: list[dict],
) -> list[dict]:
    """从候选列表中计算最终前10名排名。

    按 final_score 降序排列，取前 FINAL_RANK_COUNT 名。

    Args:
        week: 期数
        candidates: 候选列表（已含 author_type 和所有得分字段）

    Returns:
        最终排名列表
    """
    # 按最终得分降序排列
    sorted_candidates = sorted(
        candidates, key=lambda x: x["final_score"], reverse=True
    )
    top = sorted_candidates[:FINAL_RANK_COUNT]

    rankings = []
    for rank, item in enumerate(top, 1):
        rankings.append({
            "week": week,
            "rank": rank,
            "bvid": item["bvid"],
            "title": item["title"],
            "author": item["author"],
            "author_type": item.get("author_type", "unauthorized"),
            "pubdate": item.get("pubdate", 0),
            "view": item.get("view", 0),
            "like": item.get("like", 0),
            "coin": item.get("coin", 0),
            "favorite": item.get("favorite", 0),
            "share": item.get("share", 0),
            "reply": item.get("reply", 0),
            "duration": item.get("duration", 0),
            "description": item.get("description", ""),
            "base_score": item["base_score"],
            "time_factor": item["time_factor"],
            "author_weight": item.get("author_weight", 1.0),
            "final_score": item["final_score"],
            "hours_old": item.get("hours_old", 0.0),
        })

    return rankings


def save_rankings(rankings: list[dict]) -> int:
    """将排名结果存入数据库。

    Args:
        rankings: 排名结果列表

    Returns:
        存入条数
    """
    with get_db() as db:
        # 先删除该期旧排名（支持重新生成）
        if rankings:
            week = rankings[0]["week"]
            db.execute("DELETE FROM rankings WHERE week = ?", (week,))

        count = 0
        for r in rankings:
            db.execute("""
                INSERT OR REPLACE INTO rankings
                    (week, rank, bvid, title, author, author_type,
                     view, coin, favorite, base_score, time_factor,
                     author_weight, final_score, hours_old)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["week"], r["rank"], r["bvid"], r["title"], r["author"],
                r["author_type"], r["view"], r["coin"], r["favorite"],
                r["base_score"], r["time_factor"], r["author_weight"],
                r["final_score"], r["hours_old"],
            ))
            count += 1

    logger.info("已保存 %d 条排名结果（期数: %s）", count, rankings[0]["week"] if rankings else "N/A")
    return count


def get_previous_rankings(week: str) -> dict[str, dict]:
    """获取上期排名数据（用于排名变化对比）。

    Args:
        week: 当前期数，如 "2026W30"

    Returns:
        {bvid: {rank, final_score, title}} 上期排名映射
    """
    try:
        year = int(week[:4])
        week_num = int(week[5:])
        prev_week_num = week_num - 1
        prev_year = year
        if prev_week_num <= 0:
            prev_year = year - 1
            prev_week_num = 52
        prev_week = f"{prev_year}W{prev_week_num:02d}"
    except (ValueError, IndexError):
        return {}

    with get_db() as db:
        rows = db.execute(
            "SELECT bvid, rank, final_score, title FROM rankings WHERE week = ?",
            (prev_week,),
        ).fetchall()

    return {
        row["bvid"]: {
            "rank": row["rank"],
            "final_score": row["final_score"],
            "title": row["title"],
        }
        for row in rows
    }
