"""CatoN News — 交互式菜单。解决 Windows bat 中文编码问题。"""
import subprocess
import sys

MENU = """
================================================
  CatoN News (CNN) - Vocaloid Weekly Ranking
================================================

  [1] 初始化数据库
  [2] 测试爬虫 (3个关键词)
  [3] 完整爬虫
  [4] 快速爬虫 (每词1页, 不重试, 7秒间隔)
  [5] 交互式审核
  [6] 快速排名 (跳过审核)
  [7] 完整流程 (爬虫 / 审核 / 排名)
  [8] 查看排名报告
  [9] 列出所有期数
  [0] 退出

================================================
"""

COMMANDS = {
    "1": "python main.py db-init",
    "2": "python main.py crawl -k 3 -v",
    "3": "python main.py crawl -v",
    "4": "python main.py quick",
    "5": "python main.py review",
    "6": "python main.py rank",
    "7": "python main.py full",
    "8": "python main.py report",
    "9": "python main.py list",
}


def main():
    print(MENU)
    try:
        choice = input("输入选项 (0-9): ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    cmd = COMMANDS.get(choice)
    if cmd:
        print()
        subprocess.run(cmd, shell=True)
        print()
        input("按 Enter 退出...")


if __name__ == "__main__":
    main()
