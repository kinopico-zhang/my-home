"""更新日志: 从 git 历史生成逐提交的版本条目。

版本号规则 (用户定): x.y.z —— x=架构重构, y=特性, z=修复;
首个提交定 1.0.0, 之后每个提交按自身类型步进 (低段清零, 同语义化版本)。
类型从提交信息推断: 含"重构"→架构, 含"修复"/"修正"→修复, 其余→特性。
"""
import subprocess
from pathlib import Path

from .schemas import ChangelogEntry

_REPO = Path(__file__).resolve().parent.parent   # 服务就跑在仓库里
_SEP = "\x1f"                                    # git log 字段分隔 (提交信息里不会出现)

_TYPE_LABELS = {"refactor": "重构", "feat": "特性", "fix": "修复"}


def classify(subject: str) -> str:
    """提交信息 → 类型: 重构 → refactor, 修复/修正 → fix, 其余 → feat。"""
    if "重构" in subject:
        return "refactor"
    if "修复" in subject or "修正" in subject:
        return "fix"
    return "feat"


def parse_log(text: str) -> list[ChangelogEntry]:
    """git log 原始输出 (新→老) → 版本条目 (新→老)。

    逐提交编号: 最老一条定 1.0.0; refactor 进 x 段 (y/z 清零), feat 进 y 段
    (z 清零), fix 进 z 段。merge 提交与缺字段的行跳过 (不占版本号)。
    """
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        parts = line.split(_SEP)
        if len(parts) != 3:                     # 空行/脏数据跳过
            continue
        commit, date, subject = parts
        if subject.startswith("Merge "):        # 合并提交不是一次变更
            continue
        rows.append({"hash": commit, "date": date, "subject": subject})
    rows.reverse()                                # git log 新→老, 编号要老→新
    entries: list[ChangelogEntry] = []
    x, y, z = 1, 0, 0
    for i, row in enumerate(rows):
        kind = classify(row["subject"])
        if i == 0:
            version = "1.0.0"                   # 首版 1.0.0
        else:
            if kind == "refactor":
                x, y, z = x + 1, 0, 0
            elif kind == "feat":
                y, z = y + 1, 0
            else:
                z += 1
            version = f"{x}.{y}.{z}"
        entries.append(ChangelogEntry(version=version, type=kind,
                                      type_label=_TYPE_LABELS[kind], **row))
    entries.reverse()                           # 页面新→老
    return entries


def entries() -> list[ChangelogEntry]:
    """读仓库 git 历史生成条目; 不在仓库里跑 (无 .git) 返回空。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO), "log", "--date=short",
             f"--pretty=format:%h{_SEP}%ad{_SEP}%s"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_log(out)
