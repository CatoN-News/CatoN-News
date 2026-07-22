

# CatoN News

术力口新曲周榜。只收录本周新投稿。
  <p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/database-SQLite-003B57.svg" alt="SQLite">
  <img src="https://img.shields.io/badge/status-active-brightgreen.svg" alt="Status">
</p>

---

## 关于

CatoN News（简称 CNN）是一个专注于 VOCALOID 新曲的 B站 周榜。

和现有榜单不同的是，CNN **只收录并排名每周新投稿的术曲**。我们认为，每一首用心制作的新歌都值得被听到，而不是被半年前发布的爆款永远压在下面。

## 核心理念

- **仅本周新投稿** — 给每一位 P主 公平的起点
- **时间因子补偿** — 后发的新曲也能靠质量逆袭
- **人工审核** — 确认投稿类型，保证榜单公信力

## 技术栈

Python / SQLite / httpx / SQLAlchemy / rich

## 功能模块

| 模块 | 状态 |
|------|------|
| 数据抓取 | 已完成 |
| 术力口判定 | 已完成 |
| 排名计算 | 已完成 |
| 审核工具 | 已完成 |
| 报告生成 | 已完成 |

## 收录规则

| 项目 | 规则 |
|------|------|
| 统计周期 | 上周二 12:00 ~ 本周二 12:00（168 小时）|
| 数据门槛 | 播放 &gt;= 100，投币 &gt;= 20 |
| 术力口判定 | 多维度打分制，&gt;= 4 分视为术曲 |
| 排名数量 | 前 10 名 |

## 评分公式

基础分 = 播放 x 1 + 收藏 x 25 + 点赞 x 2 + 投币 x 8
时间因子 = exp(1 - T/168)
最终得分 = 基础分 x 时间因子 x 作者权重

## 项目结构

```
caton-news/
├── config.py          # 配置参数（权重、门槛、关键词、API URL）
├── models.py          # SQLAlchemy 数据库模型
├── database.py        # 数据库连接、初始化、会话管理
├── crawler.py         # B站数据抓取模块
├── classifier.py      # 术力口判定逻辑
├── ranking.py         # 排名计算（基础分、时间因子、最终得分）
├── review.py          # 命令行审核工具
├── main.py            # 主入口（一键运行完整流程）
├── menu.py            # 交互式菜单界面
├── generate_docx.py   # 排名报告文档生成
├── requirements.txt   # 依赖列表
├── .env.example       # 环境变量模板
├── .gitignore         # Git 忽略规则
├── run.bat            # Windows 一键运行脚本
├── singer_list.txt    # 歌姬名称库
├── CNN评分标准.docx    # 评分标准详细说明
└── 文件说明.txt        # 项目文件说明
```
使用
```bash
# 安装依赖
pip install -r requirements.txt

# 复制环境变量模板并填写
cp .env.example .env

# 运行完整流程
python main.py

# 或使用交互式菜单
python menu.py
```
*声明
本项目在文案撰写、文档生成及视觉设计等环节使用了 AIGC（人工智能生成内容）辅助创作。
