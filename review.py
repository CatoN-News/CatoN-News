"""
CatoN News (CNN) — 命令行审核工具
使用 Rich 库提供美观的交互式审核界面。

流程：
  1. 展示本周前30名候选
  2. 逐条审核，标记投稿者类型
  3. 重新计算最终得分
  4. 输出前10名排名报告
  5. 导出 JSON 报告
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich import box

from config import (
    AUTHOR_WEIGHT,
    BILI_VIDEO_URL,
    CANDIDATE_COUNT,
    FINAL_RANK_COUNT,
    RAW_DATA_DIR,
    REPORTS_DIR,
    REVIEW_TARGET,
)
from database import get_db
from ranking import (
    calculate_time_factor,
    calculate_final_score,
    generate_candidates,
    generate_final_rankings,
    save_rankings,
    get_previous_rankings,
)

logger = logging.getLogger(__name__)
console = Console()

# 投稿者类型映射
AUTHOR_TYPE_MAP = {
    "o": "original",
    "a": "authorized",
    "u": "unauthorized",
    "s": "skip",
    "x": "rejected",
}
AUTHOR_TYPE_LABEL = {
    "original": "本家",
    "authorized": "授权",
    "unauthorized": "未授权",
    "rejected": "否决",
}


def _fmt_pubdate(ts: int) -> str:
    """Unix 时间戳 → 可读日期字符串。"""
    if not ts:
        return "未知"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _fmt_age(hours: float) -> str:
    """小时数 → 'X天Y小时' 格式。"""
    if hours <= 0:
        return "0天0小时"
    days = int(hours // 24)
    remain = int(hours % 24)
    if days == 0:
        return f"{remain}小时"
    return f"{days}天{remain}小时"


def _display_candidate_table(candidates: list[dict], start_idx: int = 0, show: int = 10) -> None:
    """用 Rich 表格展示候选视频列表。"""
    table = Table(
        title=f"候选视频（第 {start_idx + 1} ~ {min(start_idx + show, len(candidates))} / {len(candidates)} 名）",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("投稿日期", style="cyan", width=11)
    table.add_column("标题", style="white", width=30, no_wrap=False)
    table.add_column("UP主", style="magenta", width=14)
    table.add_column("播放", justify="right", width=8)
    table.add_column("投币", justify="right", width=6)
    table.add_column("收藏", justify="right", width=6)
    table.add_column("基础分", justify="right", style="yellow", width=10)
    table.add_column("已有时长", justify="right", style="dim", width=10)
    table.add_column("类型", style="green", width=6)

    for i in range(start_idx, min(start_idx + show, len(candidates))):
        c = candidates[i]
        author_type = c.get("author_type", "unauthorized") or "unauthorized"
        at_label = AUTHOR_TYPE_LABEL.get(author_type, author_type)
        hours = c.get("hours_old", 0)

        table.add_row(
            str(i + 1),
            _fmt_pubdate(c.get("pubdate", 0)),
            c["title"][:30],
            c["author"][:14],
            str(c.get("view", 0)),
            str(c.get("coin", 0)),
            str(c.get("favorite", 0)),
            f"{c.get('base_score', 0):,.0f}",
            _fmt_age(hours),
            at_label,
        )
    console.print(table)


def _display_ranking_table(rankings: list[dict], prev_ranks: dict[str, dict]) -> None:
    """展示最终前10名排名报告，含与上期对比。"""
    table = Table(
        title="CatoN News 术力口周榜 TOP 10",
        box=box.DOUBLE_EDGE,
        show_header=True,
        header_style="bold yellow",
    )
    table.add_column("本周", style="bold", width=5)
    table.add_column("上周", style="dim", width=5)
    table.add_column("变化", width=5)
    table.add_column("投稿日", style="cyan", width=11)
    table.add_column("标题", style="white", width=22, no_wrap=False)
    table.add_column("UP主", style="magenta", width=10)
    table.add_column("播放", justify="right", width=7)
    table.add_column("收藏", justify="right", width=6)
    table.add_column("已有", justify="right", style="dim", width=8)
    table.add_column("本周分", justify="right", style="bold green", width=9)
    table.add_column("上周分", justify="right", style="dim", width=9)

    for r in rankings:
        bvid = r["bvid"]
        prev = prev_ranks.get(bvid)

        if prev is None:
            prev_rank_str = "-"
            trend = "[green]NEW[/green]"
            prev_score_str = "-"
        else:
            prev_rank_str = str(prev["rank"])
            prev_score_str = f"{prev['final_score']:,.0f}"
            dr = prev["rank"] - r["rank"]
            if dr > 0:
                trend = f"[green]+{dr}[/green]"
            elif dr < 0:
                trend = f"[red]{dr}[/red]"
            else:
                trend = "[dim]=[/dim]"

        # 排名颜色
        rank_style = ""
        if r["rank"] == 1:
            rank_style = "[bold gold1]"
        elif r["rank"] == 2:
            rank_style = "[bold silver]"
        elif r["rank"] == 3:
            rank_style = "[bold dark_orange3]"

        table.add_row(
            f"{rank_style}{r['rank']}",
            prev_rank_str,
            trend,
            _fmt_pubdate(r.get("pubdate", 0)),
            r["title"][:22],
            r["author"][:10],
            str(r.get("view", 0)),
            str(r.get("favorite", 0)),
            _fmt_age(r.get("hours_old", 0)),
            f"{r.get('final_score', 0):,.0f}",
            prev_score_str,
        )
    console.print(table)

    # 第一名详细信息
    if rankings:
        _display_champion_detail(rankings[0])


def _display_champion_detail(champion: dict) -> None:
    """展示第一名详细信息卡片。"""
    console.print()
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column("项", style="dim", width=8)
    t.add_column("值", style="bold white", width=35)

    t.add_row("曲名", champion["title"])
    t.add_row("UP主", champion["author"])
    t.add_row("B站链接", BILI_VIDEO_URL.format(champion["bvid"]))
    t.add_row("")
    t.add_row("播放", f"{champion.get('view', 0):,}")
    t.add_row("点赞", f"{champion.get('like', 0):,}")
    t.add_row("投币", f"{champion.get('coin', 0):,}")
    t.add_row("收藏", f"{champion.get('favorite', 0):,}")
    t.add_row("评论", f"{champion.get('reply', 0):,}")
    t.add_row("分享", f"{champion.get('share', 0):,}")
    t.add_row("")
    t.add_row("基础分", f"[yellow]{champion.get('base_score', 0):,.0f}[/yellow]")
    t.add_row("时间因子", f"[cyan]{champion.get('time_factor', 1.0):.4f}[/cyan]")
    t.add_row("最终得分", f"[bold green]{champion.get('final_score', 0):,.0f}[/bold green]")

    dur = champion.get("duration", 0)
    if dur:
        mins, secs = divmod(dur, 60)
        t.add_row("时长", f"{mins}分{secs}秒")
    desc = champion.get("description", "").strip()
    if desc:
        t.add_row("简介", desc)

    panel = Panel(t, title="[bold gold1] No.1 详细信息", border_style="gold1", padding=(1, 2))
    console.print(panel)


def _review_one(candidate: dict) -> Optional[str]:
    """审核单条视频，展示详情并获取用户选择。"""
    console.clear()
    console.rule("[bold cyan] CatoN News 审核系统")

    bvid = candidate["bvid"]
    video_url = BILI_VIDEO_URL.format(bvid)
    pubdate_ts = candidate.get("pubdate", 0)
    hours_old = candidate.get("hours_old", 0)

    # 详情面板
    detail = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    detail.add_column("字段", style="dim", width=10)
    detail.add_column("内容")
    detail.add_row("序号", f"#{candidate.get('candidate_rank', '?')} / {CANDIDATE_COUNT}")
    detail.add_row("标题", candidate["title"])
    detail.add_row("UP主", f"{candidate['author']} (UID: {candidate.get('mid', '?')})")
    detail.add_row("B站链接", f"[link={video_url}]{video_url}[/link]")
    detail.add_row("投稿日期", f"[bold cyan]{_fmt_pubdate(pubdate_ts)}[/bold cyan]")
    detail.add_row(
        "距截止",
        f"[bold yellow]{_fmt_age(hours_old)}[/bold yellow] (共 {hours_old:.1f} 小时)"
    )
    detail.add_row("视频时长", f"{candidate.get('duration', 0)} 秒")
    detail.add_row("")
    detail.add_row("播放", f"{candidate.get('view', 0):,}")
    detail.add_row("投币", f"{candidate.get('coin', 0):,}")
    detail.add_row("收藏", f"{candidate.get('favorite', 0):,}")
    detail.add_row("点赞", f"{candidate.get('like', 0):,}")
    detail.add_row("基础分", f"[yellow]{candidate.get('base_score', 0):,.0f}[/yellow]")
    detail.add_row("术力口分", f"{candidate.get('vocaloid_score', 0)}")

    if candidate.get("tags"):
        try:
            tags = json.loads(candidate["tags"])
            detail.add_row("标签", ", ".join(tags[:6]))
        except (json.JSONDecodeError, TypeError):
            pass

    # 视频简介
    desc = candidate.get("description", "").strip()
    if desc:
        detail.add_row("简介", desc)

    console.print(detail)
    console.print()

    # 操作提示
    console.print("[bold]请选择:[/bold]")
    console.print("  [green]o[/green] 本家         [cyan]a[/cyan] 授权       [dim]u[/dim] 未授权")
    console.print("  [yellow]s[/yellow] 跳过/有疑问   [red]x[/red] 一票否决   [bold red]q[/bold red] 退出")

    choice = Prompt.ask("\n输入选择", choices=["o", "a", "u", "s", "x", "q"], default="u")
    return AUTHOR_TYPE_MAP.get(choice, "unauthorized")


def _save_review_data(week: str, reviewed: list[dict], rejected: list[dict]) -> None:
    """保存审核结果到 raw_data/ 目录。

    只包含曲目名称和原始榜单排名，分为通过和否决两组。
    """
    from datetime import datetime

    report = {
        "week": week,
        "reviewed_at": datetime.now().isoformat(),
        "passed": [
            {
                "rank": c.get("candidate_rank", 0),
                "title": c.get("title", ""),
                "bvid": c.get("bvid", ""),
                "author": c.get("author", ""),
                "author_type": c.get("author_type", "unauthorized"),
            }
            for c in reviewed
        ],
        "rejected": [
            {
                "rank": c.get("candidate_rank", 0),
                "title": c.get("title", ""),
                "bvid": c.get("bvid", ""),
                "author": c.get("author", ""),
            }
            for c in rejected
        ],
    }

    filepath = RAW_DATA_DIR / f"{week}_reviewed.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    console.print(f"[green]审核数据已导出: {filepath}[/green]")


def _print_candidate_preview(candidates: list[dict]) -> None:
    """审核前打印所有候选视频的序号 + BV号 + 标题。"""
    table = Table(
        title="待审核列表",
        box=box.SIMPLE,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("BV号", style="cyan", width=15)
    table.add_column("标题", style="white", width=40, no_wrap=False)

    for i, c in enumerate(candidates):
        table.add_row(str(i + 1), c["bvid"], c["title"][:40])
    console.print(table)
    console.print()


def run_review(week: Optional[str] = None, auto_mode: bool = False) -> Optional[list[dict]]:
    """运行审核流程。

    Args:
        week: 期数，None 自动计算
        auto_mode: 自动模式（跳过交互，全部标记未授权，仅用于测试）

    Returns:
        最终排名列表，或 None（无数据时）
    """
    if week is None:
        from crawler import get_current_week
        week = get_current_week()

    console.rule("[bold cyan] CatoN News 审核系统启动")
    console.print(f"期数: [bold]{week}[/bold]")
    console.print()

    # 1. 获取候选池（最多100名）
    candidates = generate_candidates(week)
    if not candidates:
        console.print("[red] 本周无候选视频[/red]")
        return None

    total_pool = len(candidates)
    review_target = min(REVIEW_TARGET, total_pool)
    console.print(f"候选池: [yellow]{total_pool}[/yellow] 条，审核目标: [yellow]{review_target}[/yellow] 条")
    console.print()

    # 1.5 审核前预览列表（全部候选池）
    _print_candidate_preview(candidates)

    # 2. 逐条审核（否决补位）
    # 队列初始化：前 review_target 条
    queue: list[dict] = list(candidates[:review_target])
    next_pool_idx = review_target  # 候选池中下一个待补位的索引
    reviewed: list[dict] = []
    rejected: list[dict] = []
    i = 0

    while i < len(queue):
        c = queue[i]
        original_rank = c.get("candidate_rank", i + 1)

        if auto_mode:
            c["author_type"] = "unauthorized"
            c["author_weight"] = AUTHOR_WEIGHT["unauthorized"]
            reviewed.append(c)
            i += 1
            continue

        # Fame P 自动识别：知名P主投稿 → 自动标记本家
        from classifier import check_fame_p
        if check_fame_p(c.get("author", "")):
            c["author_type"] = "original"
            c["author_weight"] = AUTHOR_WEIGHT["original"]
            c["candidate_rank"] = original_rank
            reviewed.append(c)
            console.print(
                f"\n[bold green][Fame P][/bold green] {c['author']} — "
                f"{c.get('title', '')[:30]} → 自动标记为本家"
            )
            i += 1
            continue

        # 显示进度
        console.print(f"\n[dim]审核进度: {len(reviewed)} 已审 / {len(rejected)} 否决 / {len(queue)} 队列中[/dim]")
        _display_candidate_table(candidates, start_idx=max(0, original_rank - 3), show=7)

        choice = _review_one(c)

        if choice == "q":
            console.print(f"[yellow]审核中断，已保存前 {len(reviewed)} 条结果[/yellow]")
            break
        elif choice == "rejected":
            c["author_type"] = "rejected"
            c["candidate_rank"] = original_rank
            rejected.append(c)
            console.print(f"[red]已否决: {c['title'][:30]}[/red]")

            # 从候选池补位
            if next_pool_idx < total_pool:
                new_c = candidates[next_pool_idx]
                queue[i] = new_c  # 替换当前位置
                next_pool_idx += 1
                console.print(
                    f"[dim]补位 #{next_pool_idx}: {new_c.get('title', '')[:30]}"
                    f" (基础分: {new_c.get('base_score', 0):,.0f})[/dim]"
                )
                continue  # 重新审核当前位置（不递增 i）
            else:
                console.print("[yellow]候选池已耗尽，无法补位[/yellow]")
                i += 1
        elif choice == "skip":
            c["author_type"] = "unauthorized"
            c["author_weight"] = AUTHOR_WEIGHT["unauthorized"]
            c["candidate_rank"] = original_rank
            reviewed.append(c)
            i += 1
        else:
            c["author_type"] = choice
            c["author_weight"] = AUTHOR_WEIGHT.get(choice, 1.0)
            c["candidate_rank"] = original_rank
            reviewed.append(c)
            i += 1

    console.print(
        f"\n审核完成: {len(reviewed)} 通过 / {len(rejected)} 否决"
        f" (候选池: {total_pool}, 已拉取: {next_pool_idx})"
    )

    # 2.5 导出审核结果到 raw_data/
    _save_review_data(week, reviewed, rejected)

    # 3. 重新计算最终得分
    console.print("[cyan]重新计算最终得分...[/cyan]")
    for c in reviewed:
        if "hours_old" in c and c["hours_old"] > 0:
            deadline_ts = c["pubdate"] + int(c["hours_old"] * 3600)
        else:
            deadline_ts = c["pubdate"] + 168 * 3600

        hours_old = (deadline_ts - c["pubdate"]) / 3600.0
        time_factor = calculate_time_factor(c["pubdate"], deadline_ts)
        final_score = calculate_final_score(
            c["base_score"], time_factor, c.get("author_weight", 1.0)
        )
        c["hours_old"] = round(hours_old, 1)
        c["time_factor"] = round(time_factor, 4)
        c["final_score"] = round(final_score, 2)

    # 4. 生成最终排名
    console.print("[cyan]生成最终排名...[/cyan]")
    final_rankings = generate_final_rankings(week, reviewed)

    if not final_rankings:
        console.print("[red] 无法生成排名[/red]")
        return None

    # 5. 显示排名
    prev_ranks = get_previous_rankings(week)
    _display_ranking_table(final_rankings, prev_ranks)

    # 6. 保存到数据库
    console.print()
    if not auto_mode:
        confirm = Confirm.ask("保存排名结果到数据库?", default=True)
    else:
        confirm = True

    if confirm:
        save_rankings(final_rankings)
        console.print("[green] 排名已保存到数据库[/green]")

    # 7. 导出 JSON 报告
    report_path = REPORTS_DIR / f"{week}.json"
    report_data = {
        "meta": {
            "week": week,
            "generated_at": datetime.now().isoformat(),
            "total_candidates": len(candidates),
            "reviewed": len(reviewed),
            "ranked": len(final_rankings),
        },
        "rankings": final_rankings,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    console.print(f"[green] 报告已导出: {report_path}[/green]")

    console.rule("[bold cyan] 审核完成")
    return final_rankings


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CatoN News 审核工具")
    parser.add_argument("--week", "-w", type=str, help="期数，如 2026W30")
    parser.add_argument("--auto", action="store_true", help="自动模式（全部标记未授权）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    run_review(week=args.week, auto_mode=args.auto)
