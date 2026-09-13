"""曲库的语言标记: MusicBrainz script 码 → 使用者能看懂的语种分组。

script 标签是刮削器写进 FLAC 的 (Hant/Jpan/Latn/Hans/Kore…), 少数曲目没有
—— 按标题文字检测兜底 (假名 → 日文, 谚文 → 韩文, 汉字 → 中文, 拉丁 → 英文)。
"""
import re
import unicodedata

# Unicode 区段 → script 码 (检测用; 与 MusicBrainz 的命名一致)
_KANA_PATTERN = re.compile(r"[぀-ゟ゠-ヿ]")          # 平/片假名
_HANGUL_PATTERN = re.compile(r"[가-힯ᄀ-ᇿ]")
_CJK_PATTERN = re.compile(r"[一-鿿]")
_CYRILLIC_PATTERN = re.compile(r"[Ѐ-ӿ]")

# script 码 → 语种分组 (界面上的筛选胶囊; None = 不好分, 归"其他")
SCRIPT_LANGUAGE_NAMES: dict[str, str] = {
    "Hans": "中文", "Hant": "中文", "Hani": "中文",
    "Jpan": "日文",
    "Latn": "英文",
    "Kore": "韩文",
    "Cyrl": "俄文",
}
# 语种分组 → script 码集合 (反查, 筛选查询用)
LANGUAGE_SCRIPTS: dict[str, frozenset[str]] = {
    "中文": frozenset({"Hans", "Hant", "Hani"}),
    "日文": frozenset({"Jpan"}),
    "英文": frozenset({"Latn"}),
    "韩文": frozenset({"Kore"}),
    "俄文": frozenset({"Cyrl"}),
}
LANGUAGE_FILTERS = ("全部", "中文", "日文", "英文", "韩文", "俄文", "其他")


def language_for_script(script: str) -> str:
    """script 码 → 语种名 (认不出的归 其他)。"""
    return SCRIPT_LANGUAGE_NAMES.get(script, "其他")


def scripts_for_language(
        language: str) -> tuple[frozenset[str], bool] | None:
    """语种名 → (script 码集合, 是否取反); None = 不筛。

    其他 = 已知 script 之外的 (取反), None 与空集因此有了分别。"""
    if language in ("", "全部"):
        return None
    if language == "其他":
        known = {script for group in LANGUAGE_SCRIPTS.values()
                 for script in group}
        return frozenset(known), True
    scripts = LANGUAGE_SCRIPTS.get(language)
    return (scripts, False) if scripts is not None else None


# 检测优先级: 有假名必是日文 (汉字中日共用, 假名不共用);
# 汉字简繁没把握, 一律归 Hant (反正分组同是中文)
_SCRIPT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Jpan", _KANA_PATTERN),
    ("Kore", _HANGUL_PATTERN),
    ("Cyrl", _CYRILLIC_PATTERN),
    ("Hant", _CJK_PATTERN),
)
_LATIN_PATTERN = re.compile(r"[A-Za-z]")


def detect_script(*texts: str) -> str:
    """按文字检测 script 码 (标题/艺人名兜底; 优先级见表 _SCRIPT_PATTERNS)。

    只有标点/数字/空白的串检不出 (返回空串), 由调用方保留原 script。"""
    text = unicodedata.normalize("NFKC", " ".join(t for t in texts if t))
    for script, pattern in _SCRIPT_PATTERNS:
        if pattern.search(text):
            return script
    if _LATIN_PATTERN.search(text):
        return "Latn"
    return ""
