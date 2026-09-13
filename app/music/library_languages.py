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
        return known, True
    scripts = LANGUAGE_SCRIPTS.get(language)
    return (scripts, False) if scripts is not None else None


def detect_script(*texts: str) -> str:
    """按文字检测 script 码 (标题/艺人名兜底; 优先级 假名 > 谚文 > 汉字 > 拉丁)。

    只有标点/数字/空白的串检不出 (返回空串), 由调用方保留原 script。"""
    text = " ".join(t for t in texts if t)
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    if _KANA_PATTERN.search(text):
        return "Jpan"          # 有假名必是日文 (汉字中日共用, 假名不共用)
    if _HANGUL_PATTERN.search(text):
        return "Kore"
    if _CYRILLIC_PATTERN.search(text):
        return "Cyrl"
    if _CJK_PATTERN.search(text):
        return "Hant"          # 汉字: 简繁没把握, 归中文组即可 (分组一样)
    if re.search(r"[A-Za-z]", text):
        return "Latn"
    return ""
