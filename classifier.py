"""
CatoN News (CNN) — 术力口判定模块
两级判定制：
  Tier 1（快速通道）：标题/简介含术力口词/P主/歌姬 → 直接通过
  Tier 2（严格筛查）：无上述标记 → 多维度打分，阈值 ≥ 6
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

# ── 快速通道：命中任一即直接通过 ──────────────────────────
# 术力口强标识词
FAST_PASS_VOCALOID: list[str] = [
    "vocaloid", "术力口", "术曲", "术力口曲",
    "ボカロ", "ボーカロイド",
    "synthesizer v", "synthv", "synth v",
    "utau", "cevio", "cevio ai",
    "neutrino", "voicevox", "voiceroid",
    "ace studio", "acestudio", "ace虚拟歌姬",
    "歌声合成", "合成音声",
    "vocaloid6", "vocaloid5",
    "vocadb",  # VOCALOID数据库
    "禾念", "vsinger", "五维介质", "平行四界",
    "本家投稿", "オリジナル", "original",
]

# 歌姬名（日语+中文+其他）
FAST_PASS_SINGER: list[str] = [
    # 日语系
    "初音ミク", "初音未来", "初音", "miku",
    "鏡音リン", "鏡音レン", "鏡音", "镜音",
    "巡音ルカ", "巡音", "luka",
    "meiko", "kaito",
    "重音テト", "可不", "星界", "裏命",
    "足立レイ", "歌愛ユキ", "歌爱雪", "花隈千冬",
    "gumi", "ia", "結月ゆかり", "紲星あかり",
    "flower", "vflower", "心華", "seeu", "uni",
    "琴葉茜", "琴葉葵", "弦巻マキ",
    # 中文系
    "洛天依", "乐正绫", "言和", "心华",
    "星尘", "苍穹", "诗岸", "海伊",
    "赤羽", "minus", "牧心", "永夜minus",
    "奕夕", "yixi",
    # 英语系
    "avanna", "oliver", "yohioloid", "maika", "dex",
    "ruby", "cyber songman", "cyber diva",
    # KAF/U/可不系
    "kafu", "kaf", "sekai", "iscream",
]

# P主（知名术力口制作人）
FAST_PASS_PRODUCER: list[str] = [
    "deco*27", "ピノキオピー", "ピノキオp", "匹诺曹p",
    "ぬゆり", "nulut", "nuyuri",
    "稲葉曇", "稻叶昙", "inabakumori",
    "はるまきごはん", "春卷饭",
    "wowaka", "ハチ", "hachi",
    "kemu", "じん", "jin", "自然の敵p",
    "米津玄師", "米津玄师",
    "neru", "orangestar", "40mp",
    "doriko", "ryo", "supercell",
    "みきとp", "mikito", "mikitoP",
    "kairiki bear", "かいりきベア",
    "kanaria", "キタニタツヤ",
    "とあ", "toa", "keeno", "buzzG",
    "傘村トータ", "傘村",
    "syudou", "すりぃ", "three",
    "ツミキ", "tsumiki", "鬱p", "utsup",
    "iroha(sasaki)", "sasaki",
    "ayase", "yoasobi", "ikura",
    "giga", "reol", "kikuo",
    "cosmo@暴走p", "cosmo", "暴走p",
    "八王子p", "livetune", "kz",
    "emon(tes.)", "emon",
    "niki", "niki reverse",
    "ジミーサムp", "jimmy thumb p",
    "れるりり", "rerulili",
    "和田たけあき", "wadatakeaki", "くらげp",
    "梅とら", "umetora",
    "バルーン", "balloon", "須田景凪",
    "有機酸", "ewe", "神山羊",
    "柊キライ", "hiiragi kirai",
    "煮ル果実", "煮ル果实", "nilfruits",
    "柊マグネタイト", "hiiragi magnetite",
    "いよわ", "iyowa",
    "原口沙輔", "原口沙辅",
    "samayuzame", "サマユザメ",
    "香椎モイミ", "kashii moimi",
    "ナユタン星人", "nayutan alien",
    "aqu3ra", "ちいたな", "古川本舗",
    "maretu", "wotaku", "獅子志司",
    "r sound design", "r906",
    "john/TOOBOE", "john",
    "雄之助", "雄之介",
    "市瀬るぽ", "市濑",
    "nikiie", "尻切れ", "shirikire",
    "ぼかえり", "bokaeri",
    "serenity", "in the blue shirt",
]

# 组合成快速通道全集
FAST_PASS_ALL = (
    [t.lower() for t in FAST_PASS_VOCALOID]
    + [t.lower() for t in FAST_PASS_SINGER]
    + [t.lower() for t in FAST_PASS_PRODUCER]
)


# ── 知名P主（自动标记为本家） ──────────────────────────────

FAME_P_PRODUCERS: set[str] = {
    # 日籍P主
    "ryo", "kz", "livetune",
    "oster project",
    "dixie flatline",
    "hikarup", "hikaru p",
    "deco*27",
    "wowaka",
    "jin", "じん", "自然の敵p",
    "neru",
    "mikito p", "mikitop", "みきとp",
    "40mp", "40m p",
    "orangestar",
    "giga", "giga p",
    "reol",
    "mafumafu", "まふまふ",
    "pinocchiop", "ピノキオピー", "ピノキオp", "匹诺曹p",
    "kanaria",
    "maretu",
    "kikuo", "きくお",
    "syudou",
    "kairiki bear", "かいりきベア",
    "chinozo",
    "mimi",
    "iyowa", "いよわ",
    "atarime", "あたりめ",
    "aqu3ra",
    "kai",
    "d0tc0mmie",
    "harumaki gohan", "はるまきごはん", "春卷饭",
    "nulut", "ぬゆり", "nuyuri",
    "inabakumori", "稲葉曇", "稻叶昙",
    "hachi", "ハチ",
    "toa", "とあ",
    "keeno",
    "buzzg",
    "niki", "niki reverse",
    "emon(tes.)", "emon",
    "wotaku",
    "r906",
    "john", "john/tooboe",
    "ツミキ", "tsumiki",
    "鬱p", "utsup",
    "samayuzame", "サマユザメ",
    "香椎モイミ", "kashii moimi",
    "ナユタン星人", "nayutan alien",
    "halyosy",
    "doriko",
    "supercell",
    "八王子p",
    "ジミーサムp", "jimmy thumb p",
    "れるりり", "rerulili",
    "和田たけあき", "wadatakeaki", "くらげp",
    "梅とら", "umetora",
    "バルーン", "balloon", "須田景凪",
    "有機酸", "ewe", "神山羊",
    "柊キライ", "hiiragi kirai",
    "煮ル果実", "煮ル果实", "nilfruits",
    "柊マグネタイト", "hiiragi magnetite",
    "原口沙輔", "原口沙辅",
    "cosmo", "cosmo@暴走p", "暴走p",
    "雄之助",
    "市瀬るぽ", "市濑",
    "nikiie",
    "尻切れ", "shirikire",
    "ぼかえり", "bokaeri",
    # 华语P主
    "ilem",
    "jusf周存", "jusf",
    "阿良良木健",
    "cop",
    "乌龟sui", "乌龟",
    "纯白",
    "纳兰寻风",
    "动点p",
    "坐标p",
    "dela",
    "崩坏",
    "阿原adam", "阿原",
    "人形兔",
    "潜移默化",
    "豆腐p",
    "小熠ivac", "小熠",
    "张卡斯",
    "娅娅酱",
    "洛天依",
    # 国际P主
    "circusp",
    "crusherp", "crusher p",
    "kira",
    "ghost", "ghost and pals",
    "meltberry",
    "vane",
    "nostraightanswer",
    "lollia",
    "steampianist",
    "creep-p", "creep p",
    "bighead",
    "mcki robyns-p", "mcki robyns p",
    "ferry",
    "serenity", "in the blue shirt",
    "netsubi",
    "乐正绫", "言和",
    "kemu",
    "sasaki", "iroha(sasaki)",
    "椎名もた", "siinamota", "ぽわぽわp",
}

# 小写化版本
FAME_P_LOOKUP: set[str] = {name.lower() for name in FAME_P_PRODUCERS}


def check_fame_p(author: str) -> bool:
    """检查投稿者是否为知名P主。

    Args:
        author: UP主昵称

    Returns:
        True 如果匹配 Fame P 列表
    """
    return author.strip().lower() in FAME_P_LOOKUP


# ── Tier 2 严格筛查：打分项 ──────────────────────────────

# 强关键词（标题命中 +3）
STRONG_KEYWORDS: list[str] = [
    "vocaloid", "术力口", "术曲", "ボカロ", "ボーカロイド",
    "初音", "ミク", "重音テト", "可不",
    "synthesizer v", "synthv", "sv",
    "utau", "cevio", "neutrino",
    "voicevox", "ace studio", "ace虚拟歌姬",
    "vocaloid6", "vocaloid5", "初音未来",
]

# 歌姬名（标题/标签命中 +2）
SINGER_NAMES: list[str] = [
    "初音ミク", "初音未来", "鏡音リン", "鏡音レン", "鏡音双子",
    "巡音ルカ", "巡音流歌", "MEIKO", "KAITO",
    "重音テト", "可不", "星界", "裏命",
    "足立レイ", "歌爱雪", "花隈千冬",
    "GUMI", "IA", "結月ゆかり", "紲星あかり",
    "flower", "心華", "SeeU", "UNI",
    "琴葉茜", "琴葉葵",
    "洛天依", "乐正绫", "言和", "心华",
    "星尘", "苍穹", "诗岸", "海伊",
    "赤羽", "Minus", "牧心",
    "AVANNA", "Oliver", "YOHIOloid", "MAIKA", "DEX",
]

# 术力口标签词（标签命中 +5）
VOCALOID_TAG_KEYWORDS: list[str] = [
    "vocaloid", "术力口", "术曲", "ボカロ", "ボーカロイド",
    "初音ミク", "初音未来", "miku",
    "utau", "cevio", "synthesizer v", "synthv", "neutrino",
    "voicevox", "vocaloid原创", "vocaloidカバー",
    "vocadb", "voca", "术曲推荐",
]

# 排除词（标题命中 -3）
EXCLUDE_KEYWORDS: list[str] = [
    "翻唱", "cover", "カバー", "kobah", "reaction", "盘点", "排行榜",
    "教学", "教程", "tutorial",
    "reaction", "リアクション",
    "非术", "非术曲",
    "切片", "剪辑", "搞笑", "搞笑视频",
]

# Tier 2 通过阈值（无快速通道标识时更严格：需要至少两个信号或一个强信号）
STRICT_THRESHOLD: int = 5


def _normalize(text: str | None) -> str:
    """统一小写，处理 None。"""
    if text is None:
        return ""
    return text.lower().strip()


def _parse_tags(tags_raw: str | list | None) -> list[str]:
    """解析标签，支持 JSON 字符串或列表。"""
    if tags_raw is None:
        return []
    if isinstance(tags_raw, list):
        return tags_raw
    try:
        parsed = json.loads(tags_raw)
        if isinstance(parsed, list):
            return [str(t) for t in parsed]
        return []
    except (json.JSONDecodeError, TypeError):
        return [t.strip() for t in tags_raw.split(",") if t.strip()]


def _check_fast_pass(title_norm: str, desc_norm: str) -> bool:
    """检查标题和简介是否包含快速通道关键词。

    Args:
        title_norm: 已 normalize 的标题
        desc_norm: 已 normalize 的简介

    命中任一术力口标识词、歌姬名或P主名即返回 True。
    """
    combined = f"{title_norm} {desc_norm}"
    for kw in FAST_PASS_ALL:
        if kw in combined:
            return True
    return False


def classify_vocaloid(
    title: str,
    tags: str | list | None = None,
    duration: int = 0,
    description: str = "",
) -> Tuple[bool, int]:
    """判定一条视频是否为术曲。

    两级判定：
      Tier 1 — 标题/简介含术力口词/P主/歌姬 → 直接通过 (score=10)
      Tier 2 — 无上述标记 → 多维度打分，阈值 ≥ 5

    Args:
        title: 视频标题
        tags: 标签（JSON 字符串 或 list）
        duration: 视频时长（秒）
        description: 视频简介

    Returns:
        (is_vocaloid, score): 是否术曲 + 判定分数
    """
    # 一次 normalize，Tier 1 和 Tier 2 复用
    title_norm = _normalize(title)
    desc_norm = _normalize(description)
    tags_list = _parse_tags(tags)
    tags_text = " ".join(_normalize(t) for t in tags_list)

    # ── Tier 1: 快速通道 ──
    if _check_fast_pass(title_norm, desc_norm):
        return True, 10

    # ── Tier 2: 严格筛查 ──
    score = 0
    details: list[str] = []

    # 1. 排除项检查（-3）
    for kw in EXCLUDE_KEYWORDS:
        if kw in title_norm or kw in desc_norm:
            score -= 3
            details.append(f"排除词'{kw}': -3")
            break

    # 2. 时长过短（-5）
    if duration > 0 and duration < 30:
        score -= 5
        details.append(f"时长<30s({duration}s): -5")

    # 3. 强关键词（标题/简介 +3）
    for kw in STRONG_KEYWORDS:
        if kw in title_norm or kw in desc_norm:
            score += 3
            details.append(f"强关键词'{kw}': +3")
            break

    # 4. 术力口标签（标签 +5）
    for kw in VOCALOID_TAG_KEYWORDS:
        if kw in tags_text:
            score += 5
            details.append(f"标签词'{kw}': +5")
            break

    # 5. 歌姬名（标题/标签/简介 +2）
    for kw in SINGER_NAMES:
        kw_norm = _normalize(kw)
        if kw_norm in title_norm or kw_norm in tags_text or kw_norm in desc_norm:
            score += 2
            details.append(f"歌姬名'{kw}': +2")
            break

    is_vocaloid = score >= STRICT_THRESHOLD

    return is_vocaloid, score


def classify_batch(
    videos: list[dict],
) -> list[dict]:
    """批量判定，原地更新 is_vocaloid 和 vocaloid_score 字段。

    Args:
        videos: 视频 dict 列表，需含 title, tags, duration, description 字段

    Returns:
        更新后的 videos 列表
    """
    for v in videos:
        is_voc, score = classify_vocaloid(
            title=v.get("title", ""),
            tags=v.get("tags"),
            duration=v.get("duration", 0),
            description=v.get("description", ""),
        )
        v["is_vocaloid"] = is_voc
        v["vocaloid_score"] = score
    return videos
