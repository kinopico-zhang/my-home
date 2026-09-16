"""查询层共用的 SQL 条件与表达式: 检索键匹配 / 语种过滤 / 排序键。

语种筛选统一走曲目的 script 码 (刮削标签或文字检测来的), 专辑/艺人靠
"旗下有该语种曲目" 的 EXISTS 关联。
"""
from sqlalchemy import ColumnElement, exists, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute

from ..library_database import Album, Artist, Track
from ..library_languages import scripts_for_language
from ..library_search_keys import query_patterns

# 曲目排序: 最近添加的专辑在前, 专辑内按碟号/音轨号
_TRACK_ORDER = (Album.added_at.desc(), Album.id, Track.disc_number,
                Track.track_number, Track.id)


def _like_patterns(query: str) -> list[str]:
    """搜索词 → LIKE 模式组 (原词/简体化/去空格 × 转义 % _ \\, 带 ESCAPE '\\')。

    模式组对着 search_keys 键列扫: 拼音/声母/简繁变体都预压在键里,
    这里只归一写法; 原名列的 OR 兜底覆盖键还没回填完的老库行。"""
    def escape(text: str) -> str:
        escaped = (text.replace("\\", "\\\\").replace("%", "\\%")
                   .replace("_", "\\_"))
        return f"%{escaped}%"
    return [escape(pattern) for pattern in query_patterns(query)]


def _any_like(column: InstrumentedAttribute[str], patterns: list[str]
              ) -> ColumnElement[bool]:
    """一列 × 多模式的 OR LIKE。"""
    return or_(*[column.like(pattern, escape="\\") for pattern in patterns])


def _text_match(*columns: InstrumentedAttribute[str],
                patterns: list[str]) -> ColumnElement[bool]:
    """检索键 + 原名列们 × 多模式的 OR (键列在前, 命中面最大)。"""
    return or_(*[_any_like(column, patterns) for column in columns])


def _script_condition(language: str) -> ColumnElement[bool] | None:
    """语种 → 曲目 script 过滤条件 (全部/认不出 → None 不过滤)。"""
    resolved = scripts_for_language(language)
    if resolved is None:
        return None
    scripts, negate = resolved
    condition = Track.script.in_(scripts)
    return ~condition if negate else condition


def _album_language_condition(language: str) -> ColumnElement[bool] | None:
    """语种 → 专辑过滤条件 (旗下有该语种曲目才算)。"""
    script_condition = _script_condition(language)
    if script_condition is None:
        return None
    return exists(select(Track.id).where(
        Track.album_id == Album.id, script_condition))


def _artist_name_expression() -> ColumnElement[str]:
    """艺人名 (标签名空了用目录名, 兜底展示)。"""
    return func.coalesce(func.nullif(Artist.name, ""), Artist.directory)
