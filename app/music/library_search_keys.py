"""搜索键的生成与匹配 (拼音 / 简繁互搜 / 忽略空格的模糊匹配)。

曲目/专辑/艺人入库时把名字压成一行小写键 (原文 + 简体化 + 全拼 + 声母 +
各自去空格的变体), 查询侧把搜索词同样归一后 LIKE 键列 —— 一列扫完四种写法:
周杰伦 / 周傑倫 / zhoujielun / zjl 都能命中。歌词不预压键 (全文太大),
查询时用 原词+简体化 双 LIKE。
"""
from pypinyin import Style, lazy_pinyin
from zhconv import convert


def _variants(text: str) -> list[str]:
    """一段文本的检索变体: 原文 → 简体化 → 全拼 → 声母, 再各配一份去空格版。"""
    folded = text.casefold()
    simplified = convert(folded, "zh-hans")
    letters = lazy_pinyin(folded)
    full_pinyin = "".join(letters)
    initials = "".join(lazy_pinyin(folded, style=Style.FIRST_LETTER))
    ordered = dict.fromkeys(          # 保序去重 (简体无繁体时与原文相同)
        [folded, simplified, full_pinyin, initials])
    squashed = {variant.replace(" ", "") for variant in ordered}
    return list(dict.fromkeys([*ordered, *squashed]))


def search_keys(*texts: str) -> str:
    """若干名字段 (歌名/艺人/专辑…) → 一行检索键 (变体换行分隔)。"""
    combined = " ".join(text for text in texts if text)
    return "\n".join(_variants(combined)) if combined else ""


def query_patterns(query: str) -> list[str]:
    """搜索词 → LIKE 模式们 (原文/简体化/去空格; 调用处转义加 %)。

    查询侧不生成拼音 —— 拼音写法已在键里, LIKE 直接比对。"""
    stripped = query.strip().casefold()
    if not stripped:
        return []
    simplified = convert(stripped, "zh-hans")
    return list(dict.fromkeys(
        [stripped, simplified, stripped.replace(" ", ""),
         simplified.replace(" ", "")]))
