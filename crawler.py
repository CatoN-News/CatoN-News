"""
CatoN News (CNN) — B站爬虫模块
搜索关键词池 → 获取视频列表 → 去重 → 获取详情 → 术力口判定 → 存入数据库。
"""

import asyncio
import json
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx

from classifier import classify_vocaloid
from config import (
    BILI_API_SEARCH,
    BILI_API_VIEW,
    BILIBILI_COOKIE,
    KEYWORDS,
    MAX_RETRIES,
    MIN_COIN,
    MIN_VIEW,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF_BASE,
    SEARCH_MAX_PAGES,
    SEARCH_ORDER,
    SEARCH_PAGE_SIZE,
    SEARCH_TYPE,
    USER_AGENTS,
    CRAWL_HOURS,
    CYCLE_HOURS,
    CYCLE_START_HOUR,
    CYCLE_START_WEEKDAY,
    DEDUP_TITLE_MIN_MATCH,
    DEDUP_SIMILARITY_THRESHOLD,
)
from database import get_db

logger = logging.getLogger(__name__)


# ── 周期计算 ─────────────────────────────────────────────

def _get_deadline() -> datetime:
    """计算最近一个已过去的周二 12:00（统计截止时间）。

    规则：找到最近的周二中午 12:00。
    - 如果今天是周二但还没到 12:00，返回上周二的 12:00
    - 否则返回本周二的 12:00

    这保证了统计周期总是 [deadline-168h, deadline]，
    即完整的一个已结束的 168 小时窗口。
    """
    now = datetime.now()
    # 距离上一个周二的天数（今天是周二的话 = 0）
    days_from_tuesday = (now.weekday() - CYCLE_START_WEEKDAY) % 7

    deadline = now.replace(
        hour=CYCLE_START_HOUR, minute=0, second=0, microsecond=0
    ) - timedelta(days=days_from_tuesday)

    # 如果今天是周二但还没到中午 12:00，退回到上周二
    if days_from_tuesday == 0 and now.hour < CYCLE_START_HOUR:
        deadline -= timedelta(days=7)

    return deadline


def _deadline_to_week(dl: datetime) -> str:
    """截止时间 → 期数字符串，如 '2026W30'。"""
    year, week_num, _ = dl.isocalendar()
    return f"{year}W{week_num:02d}"


def get_current_week(offset_weeks: int = 0) -> str:
    """计算期数，如 "2026W30"。

    Args:
        offset_weeks: 0=本期（本周二截止），1=上期（上周二截止）
    """
    deadline = _get_deadline() - timedelta(days=offset_weeks * 7)
    return _deadline_to_week(deadline)


def get_week_range(offset_weeks: int = 0) -> tuple[int, int]:
    """返回统计周期的起止 Unix 时间戳。

    Args:
        offset_weeks: 0=本期（本周二截止），1=上期（上周二截止）

    周期：deadline 前 CRAWL_HOURS（两周）~ deadline
    """
    end = _get_deadline() - timedelta(days=offset_weeks * 7)
    start = end - timedelta(hours=CRAWL_HOURS)
    return int(start.timestamp()), int(end.timestamp())


def get_available_ranges() -> list[dict]:
    """返回可选的爬取时间范围列表，供用户选择。

    Returns:
        [{label, week, start_ts, end_ts, start_str, end_str}, ...]
        两组：本期（本周二截止）和上期（上周二截止）
    """
    deadline = _get_deadline()
    ranges = []

    for offset in (0, 1):
        end = deadline - timedelta(days=offset * 7)
        start = end - timedelta(hours=CRAWL_HOURS)
        rng = {
            "label": f"{start.strftime('%m/%d')} ~ {end.strftime('%m/%d')}"
                     f"  ({start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')})",
            "week": _deadline_to_week(end),
            "start_ts": int(start.timestamp()),
            "end_ts": int(end.timestamp()),
            "start_str": start.strftime("%Y-%m-%d"),
            "end_str": end.strftime("%Y-%m-%d"),
        }
        ranges.append(rng)

    return ranges


# ── 重试延迟 ─────────────────────────────────────────────
# 阶梯式延迟，避免 B站 风控

def _retry_delay(attempt: int) -> float:
    """根据重试次数返回延迟秒数。
    - 第1次重试: 5~9秒
    - 第2次重试: 10~15秒
    - 第3次重试: 17~25秒
    """
    ranges = {1: (5, 9), 2: (10, 15), 3: (17, 25)}
    lo, hi = ranges.get(attempt, (5, 9))
    return random.uniform(lo, hi)


# ── HTTP 客户端 ──────────────────────────────────────────

def _build_headers() -> dict[str, str]:
    """构建请求头，模拟浏览器。"""
    ua = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
    if BILIBILI_COOKIE:
        headers["Cookie"] = BILIBILI_COOKIE
    return headers


# ── 搜索 ─────────────────────────────────────────────────

async def _search_keyword(
    client: httpx.AsyncClient,
    keyword: str,
    page: int,
) -> Optional[list[dict]]:
    """搜索单个关键词的单个页面。

    Args:
        client: httpx 异步客户端
        keyword: 搜索关键词
        page: 页码（1-based）

    Returns:
        视频基本信息列表；None 表示全部重试失败；[] 表示 API 返回但无结果
    """
    params = {
        "search_type": SEARCH_TYPE,
        "keyword": keyword,
        "order": SEARCH_ORDER,
        "page": page,
        "page_size": SEARCH_PAGE_SIZE,
    }
    headers = _build_headers()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.get(
                BILI_API_SEARCH,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 0:
                logger.warning(
                    "搜索 '%s' 第%d页 返回异常 code=%s: %s",
                    keyword, page, data.get("code"), data.get("message", "")
                )
                return []

            result = data.get("data", {}).get("result", [])
            if not result:
                return []

            videos = []
            for item in result:
                if item.get("type") != "video":
                    continue
                videos.append({
                    "bvid": item.get("bvid", ""),
                    "title": item.get("title", "").replace(
                        '<em class="keyword">', ""
                    ).replace("</em>", ""),
                    "author": item.get("author", ""),
                    "mid": item.get("mid", 0),
                    "pubdate": item.get("pubdate", 0),
                })

            logger.debug("搜索 '%s' 第%d页: 获得 %d 条", keyword, page, len(videos))
            return videos

        except httpx.HTTPStatusError as e:
            logger.warning("搜索 '%s' 第%d页 HTTP %d (第%d次重试)",
                           keyword, page, e.response.status_code, attempt)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(_retry_delay(attempt))
        except httpx.RequestError as e:
            logger.warning("搜索 '%s' 第%d页 请求失败: %s (第%d次重试)",
                           keyword, page, e, attempt)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(_retry_delay(attempt))
        except Exception:
            logger.exception("搜索 '%s' 第%d页 未知异常", keyword, page)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(_retry_delay(attempt))

    logger.error("搜索 '%s' 第%d页 全部重试失败", keyword, page)
    return None


# ── 视频详情 ─────────────────────────────────────────────

async def _fetch_video_detail(
    client: httpx.AsyncClient,
    bvid: str,
) -> Optional[dict]:
    """获取视频详细数据。

    Args:
        client: httpx 异步客户端
        bvid: BV号

    Returns:
        包含播放量/投币/收藏/标签等详细数据的 dict，失败返回 None
    """
    params = {"bvid": bvid}
    headers = _build_headers()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.get(
                BILI_API_VIEW,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 0:
                logger.debug("视频 %s 详情获取失败 code=%s", bvid, data.get("code"))
                return None

            video_data = data.get("data", {})
            if not video_data:
                return None

            stat = video_data.get("stat", {})
            tags_raw = video_data.get("tname", "")
            # 尝试获取完整标签列表
            tag_list = []
            if "tags" in data:
                tag_list = data.get("tags", [])
            elif isinstance(tags_raw, str):
                tag_list = [tags_raw] if tags_raw else []

            # 简介前50字
            desc = (video_data.get("desc") or "").strip()
            description = desc[:50]

            return {
                "bvid": bvid,
                "title": video_data.get("title", ""),
                "author": video_data.get("owner", {}).get("name", ""),
                "mid": video_data.get("owner", {}).get("mid", 0),
                "pubdate": video_data.get("pubdate", 0),
                "view": stat.get("view", 0),
                "like": stat.get("like", 0),
                "coin": stat.get("coin", 0),
                "favorite": stat.get("favorite", 0),
                "share": stat.get("share", 0),
                "reply": stat.get("reply", 0),
                "duration": video_data.get("duration", 0),
                "description": description,
                "tags": json.dumps(tag_list, ensure_ascii=False) if tag_list else None,
            }

        except httpx.HTTPStatusError as e:
            logger.warning("视频 %s HTTP %d (第%d次重试)",
                           bvid, e.response.status_code, attempt)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(_retry_delay(attempt))
        except httpx.RequestError as e:
            logger.warning("视频 %s 请求失败: %s (第%d次重试)", bvid, e, attempt)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(_retry_delay(attempt))
        except Exception:
            logger.exception("视频 %s 处理异常", bvid)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(_retry_delay(attempt))

    logger.error("视频 %s 全部重试失败", bvid)
    return None


# ── 标题去重 ─────────────────────────────────────────────

def _dedup_by_title(videos: list[dict]) -> list[dict]:
    """标题去重：同一首歌被不同UP主投稿时，只保留数据最好的版本。

    判定规则（满足任一即视为重复）：
    1. 两标题存在 >= DEDUP_TITLE_MIN_MATCH 个连续相同字符（默认8字）
    2. 两标题的 difflib 相似度 >= DEDUP_SIMILARITY_THRESHOLD（默认0.7）

    Args:
        videos: 视频列表，需含 title, base_score 字段

    Returns:
        去重后的视频列表
    """
    import difflib

    n = len(videos)
    if n <= 1:
        return videos

    keep = [True] * n
    removed_count = 0

    for i in range(n):
        if not keep[i]:
            continue
        ti = videos[i].get("title", "")
        if not ti:
            continue

        for j in range(i + 1, n):
            if not keep[j]:
                continue
            tj = videos[j].get("title", "")
            if not tj:
                continue

            # 规则1：检查连续子串匹配
            is_dup = False
            for start in range(len(ti) - DEDUP_TITLE_MIN_MATCH + 1):
                sub = ti[start:start + DEDUP_TITLE_MIN_MATCH]
                if sub in tj:
                    is_dup = True
                    break

            # 规则2：字符串相似度
            if not is_dup:
                ratio = difflib.SequenceMatcher(None, ti, tj).ratio()
                if ratio >= DEDUP_SIMILARITY_THRESHOLD:
                    is_dup = True

            if is_dup:
                # 保留 base_score 更高的
                si = videos[i].get("base_score", 0)
                sj = videos[j].get("base_score", 0)
                if si >= sj:
                    keep[j] = False
                    logger.info(
                        "去重: '%s' <= '%s' (分低淘汰)",
                        tj[:40], ti[:40],
                    )
                else:
                    keep[i] = False
                    logger.info(
                        "去重: '%s' <= '%s' (分低淘汰)",
                        ti[:40], tj[:40],
                    )
                    break  # i 被淘汰，跳出 j 循环
                removed_count += 1

    result = [v for v, k in zip(videos, keep) if k]
    if removed_count:
        logger.info("标题去重: 移除 %d 条重复，保留 %d 条", removed_count, len(result))
    return result


# ── 主流程 ───────────────────────────────────────────────

async def run_crawler(
    limit_keywords: Optional[int] = None,
    week: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
) -> dict:
    """运行完整爬虫流程。

    Args:
        limit_keywords: 限制搜索关键词数量（测试用），None 表示全部
        week: 指定期数，None 表示自动计算
        start_ts: 爬取起始时间戳，None 自动取 get_week_range()
        end_ts: 爬取截止时间戳，None 自动取 get_week_range()

    Returns:
        统计信息 dict: {total_found, qualified, stored, week}
    """
    if week is None:
        week = get_current_week()

    if start_ts is None or end_ts is None:
        start_ts, end_ts = get_week_range()
    start_dt = datetime.fromtimestamp(start_ts)
    end_dt = datetime.fromtimestamp(end_ts)

    logger.info("=" * 60)
    logger.info("CatoN News 爬虫启动")
    logger.info("期数: %s", week)
    logger.info("收录范围: %s(周二) 12:00 ~ %s(周二) 12:00 (两周)",
                start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
    logger.info("过滤规则: 只收录此 336 小时（两周）内新投稿的视频")
    logger.info("=" * 60)

    keywords = KEYWORDS[:limit_keywords] if limit_keywords else KEYWORDS
    logger.info("关键词池: %d 个", len(keywords))

    # 获取已入库的 bvid（当前期），用于断点续传
    with get_db() as db:
        existing = {
            row["bvid"]
            for row in db.execute(
                "SELECT bvid FROM videos WHERE week = ?", (week,)
            ).fetchall()
        }
    logger.info("已入库 %d 条（本期）", len(existing))

    # ── Phase 1: 搜索 ───────────────────────────────────
    all_bvids: dict[str, dict] = {}  # bvid → 基本信息

    async with httpx.AsyncClient() as client:
        for ki, keyword in enumerate(keywords, 1):
            logger.info("[%d/%d] 搜索关键词: %s", ki, len(keywords), keyword)

            for page in range(1, SEARCH_MAX_PAGES + 1):
                results = await _search_keyword(client, keyword, page)
                if results is None:
                    # 全部重试失败（网络/风控），等待30秒后继续下一个关键词
                    logger.warning(
                        "关键词 '%s' 第%d页全部重试失败，等待30秒后继续...",
                        keyword, page,
                    )
                    await asyncio.sleep(30)
                    break
                if not results:
                    break  # 无结果，跳过该关键词后续页

                for item in results:
                    bvid = item.get("bvid", "")
                    pubdate = item.get("pubdate", 0)

                    # 时间过滤（只收录统计周期内的投稿）
                    if pubdate < start_ts or pubdate > end_ts:
                        continue

                    if bvid and bvid not in all_bvids:
                        all_bvids[bvid] = item

                # 搜索间隔
                delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
                await asyncio.sleep(delay)

            # 关键词间稍长间隔
            await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

    total_found = len(all_bvids)
    logger.info("搜索完成，去重后共 %d 条候选（时间过滤后）", total_found)

    # ── Phase 2: 获取详情 ───────────────────────────────
    qualified = 0
    stored = 0
    new_bvids = set(all_bvids.keys()) - existing

    logger.info("需要获取详情: %d 条（跳过已入库 %d 条）", len(new_bvids), len(existing))

    semaphore = asyncio.Semaphore(3)  # 并发限制

    async with httpx.AsyncClient() as client:
        tasks = []

        async def fetch_one(bvid: str):
            async with semaphore:
                detail = await _fetch_video_detail(client, bvid)
                if detail is None:
                    return None
                # 合并搜索结果的字段
                info = all_bvids.get(bvid, {})
                detail["title"] = info.get("title") or detail.get("title", "")
                detail["author"] = info.get("author") or detail.get("author", "")
                detail["mid"] = info.get("mid") or detail.get("mid", 0)
                detail["pubdate"] = info.get("pubdate") or detail.get("pubdate", 0)
                return detail

        for bvid in new_bvids:
            tasks.append(fetch_one(bvid))

        # 分批执行，每批之间输出进度
        batch_size = 10
        all_details: list[dict] = []

        for i in range(0, len(tasks), batch_size):
            batch = tasks[i : i + batch_size]
            results = await asyncio.gather(*batch)
            valid = [r for r in results if r is not None]
            all_details.extend(valid)

            progress = min(i + batch_size, len(tasks))
            logger.info("详情获取进度: %d/%d (有效 %d)", progress, len(tasks), len(all_details))

        # ── Phase 3: 判定 + 去重 + 存库 ──────────────────
        # 先过滤数据门槛 + 术力口判定 + 算基础分
        candidates: list[dict] = []
        for detail in all_details:
            if detail["view"] < MIN_VIEW or detail["coin"] < MIN_COIN:
                continue
            qualified += 1

            is_voc, voc_score = classify_vocaloid(
                title=detail["title"],
                tags=detail.get("tags"),
                duration=detail.get("duration", 0),
                description=detail.get("description", ""),
            )
            detail["is_vocaloid"] = is_voc
            detail["vocaloid_score"] = voc_score
            if not is_voc:
                continue

            base_score = (
                detail["view"] * 1.0 + detail["favorite"] * 25.0
                + detail["like"] * 2.0 + detail["coin"] * 8.0
            )
            detail["base_score"] = base_score
            candidates.append(detail)

        # 标题去重：同歌不同UP主，保留数据最好的
        candidates = _dedup_by_title(candidates)

        with get_db() as db:
            for detail in candidates:
                # 存入数据库（INSERT OR IGNORE 防止重复）
                db.execute("""
                    INSERT OR IGNORE INTO videos
                        (bvid, title, author, mid, pubdate, view, "like", coin,
                         favorite, share, reply, duration, tags, description,
                         is_vocaloid, vocaloid_score, base_score, week)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    detail["bvid"], detail["title"], detail["author"], detail["mid"],
                    detail["pubdate"], detail["view"], detail["like"], detail["coin"],
                    detail["favorite"], detail["share"], detail["reply"],
                    detail["duration"], detail.get("tags"),
                    detail.get("description", ""),
                    int(detail["is_vocaloid"]), detail["vocaloid_score"],
                    detail["base_score"], week,
                ))
                stored += 1

    logger.info("=" * 60)
    logger.info("首轮爬虫完成！统计:")
    logger.info("  搜索去重后: %d 条", total_found)
    logger.info("  过数据门槛: %d 条", qualified)
    logger.info("  判定为术曲并入库: %d 条", stored)
    logger.info("  期数: %s", week)
    logger.info("=" * 60)

    # ── 补充爬取：入库不足30条时，每个关键词再搜第一页 ────
    supplement_stored = 0
    if stored < 30:
        logger.info("⚠️ 术曲不足30首（当前 %d），启动补充爬取（仅搜第1页）...", stored)
        supplement_stored = await _run_supplement(
            client=None,  # 新建 client
            keywords=keywords,
            week=week,
            start_ts=start_ts,
            end_ts=end_ts,
            existing=existing,
        )
        stored += supplement_stored
        logger.info("补充爬取入库: %d 条，总计: %d 条", supplement_stored, stored)

    logger.info("=" * 60)
    logger.info("全部爬取完成！最终统计:")
    logger.info("  术曲入库: %d 条 (首轮%d + 补充%d)",
                stored, stored - supplement_stored, supplement_stored)
    logger.info("  期数: %s", week)
    if stored < 10:
        logger.warning("  ⚠️ 术曲总数<10，最终排名可能不足10首")
    logger.info("=" * 60)

    return {
        "total_found": total_found,
        "qualified": qualified,
        "stored": stored,
        "supplement_stored": supplement_stored,
        "week": week,
    }


# ── 快速爬取 ─────────────────────────────────────────────

async def run_quick_crawl(
    limit_keywords: Optional[int] = None,
    week: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
) -> dict:
    """快速爬取模式：每个关键词只抓第1页，不重试，关键词间等待7秒。

    适合快速获取数据概览，或网络不稳定时使用。
    """
    if week is None:
        week = get_current_week()

    if start_ts is None or end_ts is None:
        start_ts, end_ts = get_week_range()

    keywords = KEYWORDS[:limit_keywords] if limit_keywords else KEYWORDS

    logger.info("=" * 60)
    logger.info("CatoN News 快速爬取模式")
    logger.info("期数: %s | 关键词: %d 个 | 每词仅第1页 | 无重试 | 间隔7s",
                week, len(keywords))
    logger.info("=" * 60)

    # 获取已入库的 bvid
    with get_db() as db:
        existing = {
            row["bvid"]
            for row in db.execute(
                "SELECT bvid FROM videos WHERE week = ?", (week,)
            ).fetchall()
        }

    all_bvids: dict[str, dict] = {}
    skipped = 0

    async with httpx.AsyncClient() as client:
        for ki, keyword in enumerate(keywords, 1):
            logger.info("[%d/%d] 快速搜索: %s", ki, len(keywords), keyword)

            try:
                results = await _search_keyword_fast(client, keyword)
            except Exception:
                logger.warning("关键词 '%s' 快速搜索失败，跳过", keyword)
                skipped += 1
                await asyncio.sleep(7)
                continue

            if results:
                for item in results:
                    bvid = item.get("bvid", "")
                    pubdate = item.get("pubdate", 0)
                    if pubdate < start_ts or pubdate > end_ts:
                        continue
                    if bvid and bvid not in all_bvids:
                        all_bvids[bvid] = item
            else:
                skipped += 1

            # 关键词间等待 7 秒
            if ki < len(keywords):
                await asyncio.sleep(7)

    total_found = len(all_bvids)
    logger.info("快速搜索完成: %d 条候选 (跳过 %d 个关键词)", total_found, skipped)

    # 获取详情
    new_bvids = set(all_bvids.keys()) - existing
    logger.info("需要获取详情: %d 条", len(new_bvids))

    semaphore = asyncio.Semaphore(3)
    all_details: list[dict] = []

    async with httpx.AsyncClient() as client:
        async def fetch_one(bvid: str):
            async with semaphore:
                detail = await _fetch_video_detail(client, bvid)
                if detail is None:
                    return None
                info = all_bvids.get(bvid, {})
                detail["title"] = info.get("title") or detail.get("title", "")
                detail["author"] = info.get("author") or detail.get("author", "")
                detail["mid"] = info.get("mid") or detail.get("mid", 0)
                detail["pubdate"] = info.get("pubdate") or detail.get("pubdate", 0)
                return detail

        tasks = [fetch_one(bvid) for bvid in new_bvids]
        for i in range(0, len(tasks), 10):
            batch = tasks[i : i + 10]
            results = await asyncio.gather(*batch)
            valid = [r for r in results if r is not None]
            all_details.extend(valid)
            logger.info("快速详情: %d/%d", min(i + 10, len(tasks)), len(tasks))

    # 过滤 + 判定 + 存库
    qualified = 0
    stored = 0

    with get_db() as db:
        for detail in all_details:
            if detail["view"] < MIN_VIEW or detail["coin"] < MIN_COIN:
                continue
            qualified += 1

            is_voc, voc_score = classify_vocaloid(
                title=detail["title"],
                tags=detail.get("tags"),
                duration=detail.get("duration", 0),
                description=detail.get("description", ""),
            )
            detail["is_vocaloid"] = is_voc
            detail["vocaloid_score"] = voc_score
            if not is_voc:
                continue

            base_score = (
                detail["view"] * 1.0 + detail["favorite"] * 25.0
                + detail["like"] * 2.0 + detail["coin"] * 8.0
            )

            db.execute(
                """INSERT OR IGNORE INTO videos
                   (bvid, title, author, mid, pubdate, view, "like", coin,
                    favorite, share, reply, duration, tags, description,
                    is_vocaloid, vocaloid_score, base_score, week)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    detail["bvid"], detail["title"], detail["author"],
                    detail["mid"], detail["pubdate"], detail["view"],
                    detail.get("like", 0), detail["coin"],
                    detail["favorite"], detail.get("share", 0),
                    detail.get("reply", 0), detail.get("duration", 0),
                    detail.get("tags"), detail.get("description", ""),
                    int(detail["is_vocaloid"]), detail["vocaloid_score"],
                    base_score, week,
                ),
            )
            stored += 1

    logger.info("快速爬取完成: 找到%d 过门槛%d 入库%d",
                total_found, qualified, stored)

    return {
        "total_found": total_found,
        "qualified": qualified,
        "stored": stored,
        "week": week,
        "skipped_keywords": skipped,
    }


async def _search_keyword_fast(
    client: httpx.AsyncClient,
    keyword: str,
) -> Optional[list[dict]]:
    """快速搜索：单次请求，不重试。

    Returns:
        视频列表，失败返回 None
    """
    params = {
        "search_type": SEARCH_TYPE,
        "keyword": keyword,
        "order": SEARCH_ORDER,
        "page": 1,
        "page_size": SEARCH_PAGE_SIZE,
    }
    headers = _build_headers()

    try:
        response = await client.get(
            BILI_API_SEARCH,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("code") != 0:
            return None

        result = data.get("data", {}).get("result", [])
        if not result:
            return []

        videos = []
        for item in result:
            if item.get("type") != "video":
                continue
            videos.append({
                "bvid": item.get("bvid", ""),
                "title": item.get("title", "").replace(
                    '<em class="keyword">', ""
                ).replace("</em>", ""),
                "author": item.get("author", ""),
                "mid": item.get("mid", 0),
                "pubdate": item.get("pubdate", 0),
            })
        return videos

    except Exception:
        return None


async def _run_supplement(
    client: Optional[httpx.AsyncClient],
    keywords: list[str],
    week: str,
    start_ts: int,
    end_ts: int,
    existing: set[str],
) -> int:
    """补充爬取：每个关键词只搜第1页，用更长间隔降低风控。

    Returns:
        新入库的术曲数量
    """
    logger.info("--- 补充爬取开始（每关键词仅搜第1页）---")

    all_bvids: dict[str, dict] = {}
    need_client = client is None

    async with httpx.AsyncClient() as _client:
        client = _client

        for ki, keyword in enumerate(keywords, 1):
            logger.info("[补充 %d/%d] %s", ki, len(keywords), keyword)

            results = await _search_keyword(client, keyword, page=1)
            for item in results:
                bvid = item.get("bvid", "")
                pubdate = item.get("pubdate", 0)
                if pubdate < start_ts or pubdate > end_ts:
                    continue
                if bvid and bvid not in all_bvids and bvid not in existing:
                    all_bvids[bvid] = item

            # 补充爬取用更长间隔
            await asyncio.sleep(random.uniform(8, 12))

    new_bvids = list(all_bvids.keys())
    logger.info("补充搜索: 新增 %d 条未入库视频", len(new_bvids))

    if not new_bvids:
        return 0

    # 获取详情并入库
    stored = 0
    semaphore = asyncio.Semaphore(2)  # 更保守的并发

    async with httpx.AsyncClient() as client:
        async def fetch_one(bvid: str):
            async with semaphore:
                detail = await _fetch_video_detail(client, bvid)
                if detail is None:
                    return None
                info = all_bvids.get(bvid, {})
                detail["title"] = info.get("title") or detail.get("title", "")
                detail["author"] = info.get("author") or detail.get("author", "")
                detail["mid"] = info.get("mid") or detail.get("mid", 0)
                detail["pubdate"] = info.get("pubdate") or detail.get("pubdate", 0)
                return detail

        tasks = [fetch_one(bvid) for bvid in new_bvids]
        all_details: list[dict] = []

        for i in range(0, len(tasks), 10):
            batch = tasks[i: i + 10]
            results = await asyncio.gather(*batch)
            valid = [r for r in results if r is not None]
            all_details.extend(valid)
            logger.info("补充详情: %d/%d", min(i + 10, len(tasks)), len(tasks))

        # 过滤 + 判定 + 算分
        supp_candidates: list[dict] = []
        for detail in all_details:
            if detail["view"] < MIN_VIEW or detail["coin"] < MIN_COIN:
                continue
            is_voc, voc_score = classify_vocaloid(
                title=detail["title"],
                tags=detail.get("tags"),
                duration=detail.get("duration", 0),
                description=detail.get("description", ""),
            )
            detail["is_vocaloid"] = is_voc
            detail["vocaloid_score"] = voc_score
            if not is_voc:
                continue
            base_score = (
                detail["view"] * 1.0 + detail["favorite"] * 25.0
                + detail["like"] * 2.0 + detail["coin"] * 8.0
            )
            detail["base_score"] = base_score
            supp_candidates.append(detail)

        # 去重
        supp_candidates = _dedup_by_title(supp_candidates)

        with get_db() as db:
            for detail in supp_candidates:
                db.execute("""
                    INSERT OR IGNORE INTO videos
                        (bvid, title, author, mid, pubdate, view, "like", coin,
                         favorite, share, reply, duration, tags, description,
                         is_vocaloid, vocaloid_score, base_score, week)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    detail["bvid"], detail["title"], detail["author"], detail["mid"],
                    detail["pubdate"], detail["view"], detail["like"], detail["coin"],
                    detail["favorite"], detail["share"], detail["reply"],
                    detail["duration"], detail.get("tags"),
                    detail.get("description", ""),
                    int(detail["is_vocaloid"]), detail["vocaloid_score"],
                    detail["base_score"], week,
                ))
                stored += 1
                existing.add(detail["bvid"])

    logger.info("补充爬取入库: %d 条", stored)
    return stored


async def fetch_one_video(bvid: str) -> Optional[dict]:
    """获取单个视频详情（测试/手动用）。"""
    async with httpx.AsyncClient() as client:
        return await _fetch_video_detail(client, bvid)
