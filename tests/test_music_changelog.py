"""My Music 更新日志测试: 独立版本线 (2026-09-14 从 My Tesla 的日志拆出) +
条目接口 + 页面骨架 + 主页入口。渲染器与 My Tesla 共用 /static/changelog-page.js。
"""
from app.music import changelog


# ---------------------------------------------------------------- 数据
def test_versions_wellformed():
    """独立版本线从 1.0.0 起; 每版字段齐全, 文案是用户视角的一句话。"""
    vs = changelog.entries()
    assert [v.version for v in vs] == ["1.6.0", "1.5.1", "1.5.0", "1.4.1",
                                       "1.4.0", "1.3.0", "1.2.1", "1.2.0",
                                       "1.1.0", "1.0.0"]
    assert vs[0].date == "2026-09-15"
    kinds = {it.kind for it in vs[0].items}
    assert kinds <= {"新增", "改进", "修复"}   # 合并批次 (单功能批次不硬凑别的类)
    for v in vs:
        assert v.items
        assert len(v.date) == 10 and v.date[4] == "-"
        for it in v.items:
            assert it.kind in ("新增", "改进", "修复")
            assert len(it.text) >= 4
            assert "api/" not in it.text and "http" not in it.text
    assert vs[0].items[0].kind in ("新增", "修复")   # 头条是主打 (新功能或修的主 bug)
    assert "My Tesla" not in " ".join(it.text for v in vs for it in v.items)


# ---------------------------------------------------------------- 接口
def test_music_changelog_entries_endpoint(auth):
    """条目接口原样吐数据 (新→老), 字段形状与共用渲染器对齐。"""
    es = auth.get("/music/changelog/api/entries").json()
    assert [e["version"] for e in es] == [v.version for v in changelog.entries()]
    for e, v in zip(es, changelog.entries()):
        assert e["date"] == v.date
        assert e["items"] == [{"kind": it.kind, "text": it.text}
                              for it in v.items]
    assert es[0]["items"][0]["kind"] in ("新增", "修复")   # 头条是主打


# ---------------------------------------------------------------- 页面
def test_music_changelog_page_skeleton(auth):
    """更新日志页: 与 My Tesla 同一套骨架, 数据源/资源换成听歌应用自己的。"""
    html = auth.get("/music/changelog").text
    html += auth.get("/static/changelog-page.js?v=1").text
    for frag in [
        "<title>更新日志 · My Music</title>",
        '<a href="/music/">听歌</a>',                            # 回主页
        '<a class="on" href="/music/changelog">更新日志</a>',   # 菜单 (自身亮)
        'id="brand-menu"', 'id="logout"',
        'id="entries"', 'id="list"', 'id="loading"', 'id="error"', 'id="retry"',
        'data-changelog-api="/music/changelog/api/entries"',   # 数据源 (body)
        'href="/music/static/manifest.json"',                  # 独立 PWA 身份
        'const KIND_CLS = { "新增": "add", "改进": "imp", "修复": "fix" };',
        "更新日志 · My Music",
    ]:
        assert frag in html, f"更新日志页缺少 {frag}"
    assert "lastpage.js" not in html    # 上次停留页是 Tesla 应用的概念


def test_changelog_link_in_music_menu(auth):
    """听歌主页的品牌菜单里有更新日志入口 (应用内视图, 不再整页跳走)。"""
    assert '<button id="changelog-link">更新日志</button>' \
        in auth.get("/music").text
