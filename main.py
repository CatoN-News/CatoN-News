"""
CatoN News (CNN) — 主入口
完整的爬虫→审核→排名流程。

用法:
    python main.py crawl          # 只运行爬虫
    python main.py review         # 只运行审核
    python main.py full           # 完整流程（爬虫 → 审核 → 排名）
    python main.py rank           # 只计算排名（不审核，全部标记未授权）
    python main.py report [week]  # 查看某期排名报告
    python main.py db-init        # 初始化数据库
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich import box

from config import LOG_FORMAT, LOG_DATE_FORMAT, LOG_LEVEL, BILI_VIDEO_URL
from database import init_db, get_db

console = Console()


def setup_logging(verbose: bool = False) -> None:
    """配置日志。"""
    level = logging.DEBUG if verbose else getattr(logging, LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )
    # 降低 httpx 的日志级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def cmd_db_init() -> None:
    """初始化数据库。"""
    init_db()
    console.print("[green]✅ 数据库初始化完成[/green]")


def _select_time_range(week: Optional[str]) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """选择爬取时间范围。如果 week 已指定则直接返回，否则交互式选择。

    Returns:
        (week, start_ts, end_ts)
    """
    from crawler import get_available_ranges

    if week is not None:
        return week, None, None

    ranges = get_available_ranges()
    console.print()
    console.print("[bold]选择爬取时间范围:[/bold]")
    console.print(f"  [1] 本期 — {ranges[0]['label']}")
    console.print(f"  [2] 上期 — {ranges[1]['label']}")
    choice = input("\n输入选择 (1/2, 默认 1): ").strip() or "1"

    if choice == "2":
        r = ranges[1]
    else:
        r = ranges[0]

    console.print(f"\n[cyan]已选择: {r['start_str']} ~ {r['end_str']}  (期数: {r['week']})[/cyan]")
    return r["week"], r["start_ts"], r["end_ts"]


def cmd_crawl(week: Optional[str] = None, limit: Optional[int] = None, verbose: bool = False) -> None:
    """运行爬虫。"""
    setup_logging(verbose)
    from crawler import run_crawler

    week, start_ts, end_ts = _select_time_range(week)

    console.print(f"[cyan]🕷️ 启动爬虫 — 期数: {week}[/cyan]")
    result = asyncio.run(run_crawler(
        limit_keywords=limit, week=week,
        start_ts=start_ts, end_ts=end_ts,
    ))

    console.print()
    console.print("[green]✅ 爬虫完成[/green]")
    console.print(f" 期数: {result['week']}")
    console.print(f" 搜索到: {result['total_found']} 条")
    console.print(f" 过门槛: {result['qualified']} 条")
    console.print(f" 入库术曲: {result['stored']} 条")


def cmd_quick(week: Optional[str] = None, limit: Optional[int] = None, verbose: bool = False) -> None:
    """快速爬取：每个关键词只抓第1页，不重试，间隔7秒。"""
    setup_logging(verbose)
    from crawler import run_quick_crawl

    week, start_ts, end_ts = _select_time_range(week)

    console.print(f"[cyan]快速爬虫 — 期数: {week}[/cyan]")
    console.print("[dim]模式: 每词仅第1页 / 不重试 / 间隔7秒[/dim]")
    result = asyncio.run(run_quick_crawl(
        limit_keywords=limit, week=week,
        start_ts=start_ts, end_ts=end_ts,
    ))

    console.print()
    console.print("[green]快速爬虫完成[/green]")
    console.print(f" 期数: {result['week']}")
    console.print(f" 搜索到: {result['total_found']} 条")
    console.print(f" 过门槛: {result['qualified']} 条")
    console.print(f" 入库术曲: {result['stored']} 条")
    if result.get("skipped_keywords"):
        console.print(f" 跳过关键词: {result['skipped_keywords']} 个")


def cmd_review(week: Optional[str] = None, auto: bool = False, verbose: bool = False) -> None:
    """运行审核流程。"""
    setup_logging(verbose)
    from review import run_review
    run_review(week=week, auto_mode=auto)


def cmd_rank(week: Optional[str] = None, verbose: bool = False) -> None:
    """不审核，直接按基础分排名（全部标记未授权）。"""
    setup_logging(verbose)
    from crawler import get_current_week
    from ranking import generate_candidates, generate_final_rankings, save_rankings, get_previous_rankings
    from review import _display_ranking_table

    if week is None:
        week = get_current_week()

    console.print(f"[cyan]📊 快速排名 — 期数: {week}[/cyan]")
    candidates = generate_candidates(week)
    if not candidates:
        console.print("[red]❌ 无候选视频[/red]")
        return

    # 全部标记未授权
    for c in candidates:
        c["author_type"] = "unauthorized"
        c["author_weight"] = 1.0
        c["final_score"] = c["base_score"] * c.get("time_factor", 1.0)

    rankings = generate_final_rankings(week, candidates)
    prev_ranks = get_previous_rankings(week)
    _display_ranking_table(rankings, prev_ranks)

    save_rankings(rankings)
    console.print("[green]✅ 排名已保存[/green]")


def cmd_full(week: Optional[str] = None, limit: Optional[int] = None, auto: bool = False, verbose: bool = False) -> None:
    """完整流程：爬虫 → 审核 → 排名。"""
    setup_logging(verbose)
    from crawler import run_crawler

    week, start_ts, end_ts = _select_time_range(week)

    # Step 1: 爬虫
    console.print("[cyan]=" * 50)
    console.print("Step 1/3: 爬虫")
    console.print("=" * 50)
    result = asyncio.run(run_crawler(
        limit_keywords=limit, week=week,
        start_ts=start_ts, end_ts=end_ts,
    ))

    if result["stored"] == 0 and result["total_found"] == 0:
        console.print("[red]❌ 爬虫未获取到数据，终止[/red]")
        return

    # Step 2: 审核
    console.print()
    console.print("[cyan]=" * 50)
    console.print("Step 2/3: 审核")
    console.print("=" * 50)
    from review import run_review
    final = run_review(week=week, auto_mode=auto)

    if final is None:
        console.print("[red]❌ 审核未产生结果[/red]")
        return

    console.print()
    console.print("[green]✅ 完整流程完成！[/green]")


def cmd_report(week: Optional[str] = None, verbose: bool = False) -> None:
    """查看排名报告。"""
    setup_logging(verbose)
    from crawler import get_current_week

    if week is None:
        week = get_current_week()

    with get_db() as db:
        rows = db.execute("""
            SELECT * FROM rankings
            WHERE week = ?
            ORDER BY rank
        """, (week,)).fetchall()

    if not rows:
        console.print(f"[yellow]⚠️ 期数 {week} 无排名数据[/yellow]")
        return

    from review import AUTHOR_TYPE_LABEL, get_previous_rankings, _display_ranking_table

    prev_ranks = get_previous_rankings(week)
    rankings = [dict(r) for r in rows]
    _display_ranking_table(rankings, prev_ranks)


def cmd_list_weeks() -> None:
    """列出所有已有数据的期数。"""
    with get_db() as db:
        video_weeks = {
            row["week"] for row in
            db.execute("SELECT DISTINCT week FROM videos ORDER BY week DESC").fetchall()
        }
        rank_weeks = {
            row["week"] for row in
            db.execute("SELECT DISTINCT week FROM rankings ORDER BY week DESC").fetchall()
        }

    table = Table(title="数据概览", box=box.ROUNDED)
    table.add_column("期数", style="cyan")
    table.add_column("有爬虫数据", justify="center")
    table.add_column("有排名", justify="center")

    all_weeks = sorted(video_weeks | rank_weeks, reverse=True)
    for w in all_weeks:
        table.add_row(
            w,
            "✅" if w in video_weeks else "❌",
            "✅" if w in rank_weeks else "❌",
        )

    if not all_weeks:
        console.print("[dim]暂无数据[/dim]")
    else:
        console.print(table)


# ── CLI 入口 ────────────────────────────────────────────

def main():
    """CatoN News CLI 入口（使用 argparse，兼容 Python 3.9）。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="CatoN News (CNN) — 术力口周榜",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py crawl              # 运行爬虫
  python main.py crawl -k 3         # 只搜前3个关键词（测试用）
  python main.py quick              # 快速爬取（每词1页/不重试/7秒间隔）
  python main.py review             # 交互式审核
  python main.py review --auto      # 自动审核（全部标记未授权）
  python main.py rank               # 快速排名（跳过审核）
  python main.py full               # 完整流程（爬虫→审核→排名）
  python main.py report 2026W30     # 查看排名报告
  python main.py db-init            # 初始化数据库
  python main.py list               # 列出所有期数
        """,
    )
    parser.add_argument(
        "--no-pause", action="store_true",
        help="结束后不暂停（用于脚本/定时任务）"
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # db-init
    subparsers.add_parser("db-init", help="初始化数据库")

    # crawl
    p_crawl = subparsers.add_parser("crawl", help="完整爬虫（54关键词x5页/阶梯重试）")
    p_crawl.add_argument("-w", "--week", type=str, default=None, help="指定期数（如 2026W30）")
    p_crawl.add_argument("-k", "--limit", type=int, default=None, help="限制关键词数量（测试用）")
    p_crawl.add_argument("-v", "--verbose", action="store_true", help="详细日志")

    # quick
    p_quick = subparsers.add_parser("quick", help="快速爬虫（每词1页/不重试/间隔7秒）")
    p_quick.add_argument("-w", "--week", type=str, default=None, help="指定期数（如 2026W30）")
    p_quick.add_argument("-k", "--limit", type=int, default=None, help="限制关键词数量（测试用）")
    p_quick.add_argument("-v", "--verbose", action="store_true", help="详细日志")

    # review
    p_review = subparsers.add_parser("review", help="交互式审核（候选100→审30/否决补位/FameP自动）")
    p_review.add_argument("-w", "--week", type=str, default=None, help="指定期数（如 2026W30）")
    p_review.add_argument("--auto", action="store_true", help="自动模式（全部标记未授权）")
    p_review.add_argument("-v", "--verbose", action="store_true", help="详细日志")

    # rank
    p_rank = subparsers.add_parser("rank", help="快速排名（跳过审核/全部未授权）")
    p_rank.add_argument("-w", "--week", type=str, default=None, help="指定期数（如 2026W30）")
    p_rank.add_argument("-v", "--verbose", action="store_true", help="详细日志")

    # full
    p_full = subparsers.add_parser("full", help="完整流程（爬虫→审核→排名）")
    p_full.add_argument("-w", "--week", type=str, default=None, help="指定期数（如 2026W30）")
    p_full.add_argument("-k", "--limit", type=int, default=None, help="限制关键词数量（测试用）")
    p_full.add_argument("--auto", action="store_true", help="自动审核（跳过交互）")
    p_full.add_argument("-v", "--verbose", action="store_true", help="详细日志")

    # report
    p_report = subparsers.add_parser("report", help="查看排名报告")
    p_report.add_argument("week", nargs="?", default=None, help="期数（如 2026W30）")
    p_report.add_argument("-v", "--verbose", action="store_true", help="详细日志")

    # list
    subparsers.add_parser("list", help="列出所有期数及数据状态")

    args = parser.parse_args()

    if args.command == "db-init" or args.command is None:
        cmd_db_init()
    elif args.command == "crawl":
        cmd_crawl(week=args.week, limit=args.limit, verbose=args.verbose)
    elif args.command == "quick":
        cmd_quick(week=args.week, limit=args.limit, verbose=args.verbose)
    elif args.command == "review":
        cmd_review(week=args.week, auto=args.auto, verbose=args.verbose)
    elif args.command == "rank":
        cmd_rank(week=args.week, verbose=args.verbose)
    elif args.command == "full":
        cmd_full(week=args.week, limit=args.limit, auto=args.auto, verbose=args.verbose)
    elif args.command == "report":
        cmd_report(week=args.week, verbose=args.verbose)
    elif args.command == "list":
        cmd_list_weeks()
    else:
        parser.print_help()

    # 程序结束后暂停，避免窗口自动关闭
    # 使用 --no-pause 参数可跳过（用于脚本/定时任务）
    if not getattr(args, "no_pause", False):
        print()
        input("按 Enter 键退出...")


if __name__ == "__main__":
    main()
