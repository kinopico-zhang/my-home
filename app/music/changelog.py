"""My Music 更新日志数据: 每个版本 = 一批改动的合并, 文案站在使用者视角。

不逐提交记版本 (一个版本可以同时含多个修复和多个功能); 版本号 x.y.z ——
x 大改版 · y 新功能 · z 问题修复, 新批次加在最上面 (新→老)。
听歌应用自己的版本线 (2026-09-14 起与 My Tesla 的更新日志各自独立)。
条目按版本段分家: 1.8 / 1.7 / 1.4–1.6 / 1.0–1.3 各一个数据文件。
"""
from typing import Final

from ..schemas import ChangelogVersion
from .changelog_versions_1_0_to_1_3 import VERSIONS_1_0_TO_1_3
from .changelog_versions_1_4_to_1_6 import VERSIONS_1_4_TO_1_6
from .changelog_versions_1_7 import VERSIONS_1_7
from .changelog_versions_1_8 import VERSIONS_1_8

VERSIONS: Final[list[ChangelogVersion]] = (VERSIONS_1_8 + VERSIONS_1_7
                                           + VERSIONS_1_4_TO_1_6
                                           + VERSIONS_1_0_TO_1_3)


def entries() -> list[ChangelogVersion]:
    """全部版本, 新→老。"""
    return VERSIONS
