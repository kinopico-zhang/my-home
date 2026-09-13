"""更新日志页测试: git 历史解析 (版本号步进规则) + 条目接口 + 页面骨架 + 入口。

版本号规则: x.y.z —— x=架构重构, y=特性, z=修复; 首个提交定 1.0.0,
之后每个提交按类型步进 (低段清零); merge 提交不占号。条目按新→老输出。
"""
import subprocess

from app import changelog

SEP = changelog._SEP   # pylint: disable=protected-access


def _log(*rows: tuple[str, str, str]) -> str:
    """行 (hash, date, subject) → git log 原始输出格式。"""
    return "\n".join(SEP.join(r) for r in rows)


# ---------------------------------------------------------------- 解析规则
def test_parse_log_version_march():
    """1.0.0 起: 特性进 y (z 清零), 修复进 z, 重构进 x (y/z 清零); 新→老输出。"""
    es = changelog.parse_log(_log(
        ("aaa1007", "2026-09-04", "文案统一"),        # git log 顺序: 新→老
        ("aaa1006", "2026-09-04", "修正地图居中"),
        ("aaa1005", "2026-09-03", "内联脚本重构抽出"),
        ("aaa1004", "2026-09-03", "新增地图页"),
        ("aaa1003", "2026-09-02", "修复充电页排序"),
        ("aaa1002", "2026-09-02", "新增充电页"),
        ("aaa1001", "2026-09-01", "初始提交"),
    ))
    assert [e.version for e in es] == [
        "2.1.0",   # 文案统一 (feat): 2.0.1 → 2.1.0
        "2.0.1",   # 修正 (fix)
        "2.0.0",   # 重构 (refactor): 1.2.0 → 2.0.0
        "1.2.0",   # 新增地图页 (feat): 1.1.1 → 1.2.0
        "1.1.1",   # 修复 (fix)
        "1.1.0",   # 新增充电页 (feat): 1.0.0 → 1.1.0
        "1.0.0",   # 首版
    ]
    assert [(e.type, e.type_label) for e in es[:3]] == [
        ("feat", "特性"), ("fix", "修复"), ("refactor", "重构")]
    assert es[0].subject == "文案统一" and es[0].date == "2026-09-04"


def test_parse_log_skips_merge_and_bad_lines():
    """merge 提交与缺字段的行不占版本号。"""
    es = changelog.parse_log("\n".join([
        SEP.join(("aaa2003", "2026-09-03", "新功能")),   # 新→老
        "两字段\x1f的脏行",
        SEP.join(("aaa2002", "2026-09-02", "Merge branch 'x' into main")),
        "Merge branch 'feature' of ...",
        SEP.join(("aaa2001", "2026-09-01", "初始提交")),
    ]))
    assert [e.version for e in es] == ["1.1.0", "1.0.0"]   # merge 没占号
    assert changelog.parse_log("") == []


def test_classify_keywords():
    assert changelog.classify("内联 JS 重构抽出") == "refactor"
    assert changelog.classify("修复费用筛选 400") == "fix"
    assert changelog.classify("修正地图居中") == "fix"
    assert changelog.classify("充电地图页: 热力图") == "feat"


# ---------------------------------------------------------------- 接口
def test_changelog_entries_endpoint(auth):
    """真实仓库: 条目数对得上提交数, 最新一条是 HEAD, 版本号新→老不升。"""
    es = auth.get("/tesla/changelog/api/entries").json()
    count = int(subprocess.run(
        ["git", "-C", str(changelog._REPO), "rev-list", "--count", "HEAD"],   # pylint: disable=protected-access
        capture_output=True, text=True, check=True).stdout.strip())
    assert count >= 100
    assert len(es) == count                       # 无 merge 历史, 一一对应
    head = subprocess.run(
        ["git", "-C", str(changelog._REPO), "rev-parse", "--short", "HEAD"],  # pylint: disable=protected-access
        capture_output=True, text=True, check=True).stdout.strip()
    assert es[0]["hash"] == head
    assert es[-1]["version"] == "1.0.0"           # 最老一条是首版
    vs = [tuple(int(n) for n in e["version"].split(".")) for e in es]
    assert all(a >= b for a, b in zip(vs, vs[1:]))   # 新→老不升序违反
    assert {e["type"] for e in es} <= {"feat", "fix", "refactor"}


def test_entries_when_git_unreadable(auth, monkeypatch, tmp_path):
    """git 历史读不到: 返回空列表而不是 500 (前端落"没有版本历史")。

    注意 pytest 的 tmp 在仓库内部 (.pytest-tmp), git -C 会向上找到 .git,
    所以用不存在的路径触发 subprocess 失败 (与无 .git 同走一个 except)。
    """
    monkeypatch.setattr(changelog, "_REPO", tmp_path / "不存在的目录")
    assert changelog.entries() == []
    assert auth.get("/tesla/changelog/api/entries").json() == []


# ---------------------------------------------------------------- 页面
def test_changelog_page_skeleton(auth):
    """更新日志页: 版本号规则说明 + 逐条目行 (版本徽标/类型胶囊/说明/日期哈希)。"""
    html = auth.get("/tesla/changelog").text
    html += auth.get("/tesla/static/changelog.js?v=1").text
    for frag in [
        "<title>更新日志 · My Tesla</title>",
        '<a href="/tesla/settings">软件设置</a>',        # 菜单 (子页, 自身不亮)
        'id="brand-menu"', 'id="logout"',
        "逐提交步进", "1.0.0</b> 为首版",                # x.y.z 规则说明
        'id="entries"', 'id="list"', 'id="loading"', 'id="error"', 'id="retry"',
        '"/tesla/changelog/api/entries"',               # 数据源
        'class="v-badge"', 'class="v-chip ',            # 徽标 + 类型胶囊
        '.v-chip.feat', '.v-chip.fix', '.v-chip.refactor',
        "更新日志 · My Tesla",
    ]:
        assert frag in html, f"更新日志页缺少 {frag}"


def test_changelog_link_in_settings(auth):
    """软件设置页'关于'卡里有更新日志入口。"""
    assert '<a class="about-link" href="/tesla/changelog">更新日志' \
        in auth.get("/tesla/settings").text


def test_changelog_in_lastpage_and_login_whitelist(auth):
    """上次停留页/登录回跳白名单收录 (子页可停留, 直链可回跳)。"""
    lastpage = auth.get("/tesla/static/lastpage.js?v=1").text
    assert '"/tesla/settings", "/tesla/changelog"]' in lastpage
    login_js = auth.get("/tesla/static/login.js?v=1").text
    assert "live|settings|changelog)" in login_js
