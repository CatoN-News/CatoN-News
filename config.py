"""
CatoN News (CNN) — 配置模块
所有硬编码参数集中管理，敏感配置从 .env 读取。
"""

import os
import sys
from pathlib import Path

# ── Windows UTF-8 支持（必须在任何输出之前执行） ─────────
# 解决 Windows 终端 GBK 编码导致中文/emoji 乱码的问题
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.encoding.lower() in ("gbk", "cp936", "cp1252"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ── 项目路径 ─────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
RAW_DATA_DIR = PROJECT_ROOT / "raw_data"
DATABASE_PATH = DATA_DIR / "cnn.db"

# 确保目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── 环境变量（从 .env 加载） ────────────────────────────
def _load_dotenv():
    """手动加载 .env，避免引入额外依赖。"""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

_load_dotenv()

# B站 Cookie（用于获取完整数据，未登录也能跑但数据可能受限）
BILIBILI_COOKIE: str = os.getenv("BILIBILI_COOKIE", "")

# 管理员密码（Phase 1 明文，后续迁移到 bcrypt）
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")

# ── 统计周期 ─────────────────────────────────────────────
CRAWL_HOURS: int = 336               # 爬取范围：两周（336小时）
CYCLE_HOURS: int = 168                # 时间因子归一化基准：一周（168小时）
CYCLE_START_WEEKDAY: int = 1          # 周二（Python weekday: 0=Mon, 1=Tue）
CYCLE_START_HOUR: int = 12            # 中午 12:00

# ── 数据门槛 ─────────────────────────────────────────────
MIN_VIEW: int = 100                   # 最低播放量
MIN_COIN: int = 20                    # 最低投币数

# ── 基础分权重 ───────────────────────────────────────────
W_VIEW: float = 1.0
W_LIKE: float = 2.0
W_COIN: float = 8.0
W_FAVORITE: float = 25.0
W_SHARE: float = 0.0                  # 分享暂不计入
W_REPLY: float = 0.0                  # 评论暂不计入

# ── 时间因子 ─────────────────────────────────────────────
TIME_ALPHA: float = 1.0               # 时间衰减系数（推荐 1.0）

# ── 投稿者权重 ──────────────────────────────────────────
AUTHOR_WEIGHT: dict[str, float] = {
    "original": 1.03,
    "authorized": 1.01,
    "unauthorized": 1.00,
}

# ── 排名数量 ─────────────────────────────────────────────
CANDIDATE_COUNT: int = 100            # 候选池总数
FINAL_RANK_COUNT: int = 10            # 最终排名数
REVIEW_TARGET: int = 30               # 审核目标数（否决后自动补位）

# ── B站 API 配置 ─────────────────────────────────────────
BILI_API_SEARCH = "https://api.bilibili.com/x/web-interface/search/type"
BILI_API_VIEW = "https://api.bilibili.com/x/web-interface/view"
BILI_VIDEO_URL = "https://www.bilibili.com/video/{}"

# 搜索参数
SEARCH_PAGE_SIZE: int = 50            # 每页条数
SEARCH_MAX_PAGES: int = 5             # 每个关键词搜索页数
DEDUP_TITLE_MIN_MATCH: int = 5         # 标题去重：连续N个字符相同视为同一首歌（5=中日文都适用，太低会误杀）
DEDUP_SIMILARITY_THRESHOLD: float = 0.7 # 标题去重：相似度阈值（备用，>=此值视为重复）
SEARCH_ORDER: str = "pubdate"         # 按发布时间排序
SEARCH_TYPE: str = "video"            # 搜索类型：视频

# 请求控制
REQUEST_DELAY_MIN: float = 2.0        # 请求最小间隔（秒）
REQUEST_DELAY_MAX: float = 5.0        # 请求最大间隔（秒）
MAX_RETRIES: int = 3                  # 最大重试次数
RETRY_BACKOFF_BASE: float = 2.0       # 重试指数退避基数
REQUEST_TIMEOUT: float = 15.0         # 请求超时（秒）

# ── 爬虫关键词池 ─────────────────────────────────────────
KEYWORDS: list[str] = [
    # 引擎/技术标签
    "VOCALOID",
    "术力口",
    "术曲",
    "ボカロ",
    "ボーカロイド",
    "VOCALOIDオリジナル",
    "VOCALOID新曲",
    "Synthesizer V",
    "SynthV",
    "UTAU",
    "CeVIO",
    "CeVIO AI",
    "NEUTRINO",
    "VOICEROID",
    "VOICEVOX",
    "ACE Studio",
    "歌声合成",
    # 日语歌姬
    "初音ミク",
    "鏡音リン",
    "鏡音レン",
    "巡音ルカ",
    "MEIKO",
    "KAITO",
    "重音テト",
    "可不",
    "星界",
    "裏命",
    "足立レイ",
    "歌愛ユキ",
    "花隈千冬",
    "GUMI",
    "IA",
    "結月ゆかり",
    "flower",
    "紲星あかり",
    "琴葉茜",
    "琴葉葵",
    "弦巻マキ",
    # 中文歌姬
    "洛天依",
    "乐正绫",
    "言和",
    "心华",
    "星尘",
    "苍穹",
    "诗岸",
    "海伊",
    "赤羽",
    "Minus",
    "牧心",
    "永夜Minus",
    # P主/N榜相关
    "ボカロ曲",
    "ボカロオリジナル曲",
    "Vocaloidオリジナル",
    "週刊VOCALOID",
]

# ── User-Agent 池（模拟浏览器） ──────────────────────────
USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

# ── 日志配置 ─────────────────────────────────────────────
LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
