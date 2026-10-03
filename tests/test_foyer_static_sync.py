"""首厅静态与子仓引用对账: 子仓页面引用的 /static/* 必须在首厅存在。

2026-10-03 实锤: my-money 1.7.0/1.7.1 在子仓里新建的 no-zoom.js /
back-swipe.js 只进了子仓, 组合仓 /static (8500 线上真身) 没有双胞胎 ——
线上 404, 禁缩放与右划返回在手机上整个是死的 (各仓门禁只看各自仓里的
文件, 这层缺口全瞎)。此测试守装配这一层:
- 存在性: 任何子仓 html 引用的裸 /static/ 路径, 首厅目录里必须有文件;
- 双胞胎一致: no-zoom.js / back-swipe.js 与带它的子仓副本逐字节相同;
- 首厅三份页 css 带 touch-action: pan-y (1.7.0 禁缩放 — 三应用的
  scoped 登录/注册/账号页运行时用的都是首厅这份);
- 壳自家的三张门厅页也装了 no-zoom (meta + body 后第一条脚本,
  2026-10-03 补齐, 与三应用同款);
- 版本化缓存头: ?v= 的静态回 immutable (?v= 家规配套, 手机公网导航提速)。
"""
import re
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as m

ROOT = Path(__file__).resolve().parent.parent
FOYER = ROOT / "app" / "home" / "static"
# 引号紧贴 /static/ 才算首厅引用 (排除 /bookkeeping/static 这类应用自挂的)
REF = re.compile(r"""["'](/static/[^"'?]+)""")


def _submodule_pages() -> list[Path]:
    return sorted(p for p in (ROOT / "apps").glob("*/app/**/static/**/*.html")
                  if p.is_file())


def test_submodule_foyer_refs_exist():
    """三应用页面引用的首厅资产, 首厅目录里都得有 (404 类问题再犯即红)。"""
    pages = _submodule_pages()
    assert len(pages) >= 15, "子仓页面枚举异常 (glob 失配会静默跳过)"
    assert any(p.name == "settings.html" for p in pages)   # my-money 子页在
    assert any(p.name == "login.html" for p in pages)      # 首厅页在
    for page in pages:
        refs = REF.findall(page.read_text(encoding="utf-8"))
        for ref in refs:
            assert (FOYER / ref.removeprefix("/static/")).is_file(), \
                f"{page.relative_to(ROOT)} 引用 {ref}, 首厅没有对应文件"


def test_foyer_twins_identical():
    """no-zoom.js / back-swipe.js: 首厅副本与子仓副本逐字节相同 (漂移即红)。"""
    for name in ("no-zoom.js", "back-swipe.js"):
        foyer = (FOYER / name).read_bytes()
        twins = list((ROOT / "apps").glob(f"*/app/home/static/{name}"))
        assert twins, f"没有任何子仓带 {name} (首厅这份成了无源之水)"
        for twin in twins:
            assert twin.read_bytes() == foyer, \
                f"{twin.relative_to(ROOT)} 与首厅的 {name} 漂移了"


def test_foyer_css_pinch_guard():
    """首厅三份页 css 收口捏合 (body touch-action: pan-y, 1.7.0 全应用禁缩放)。"""
    for name in ("login-page.css", "register-page.css", "accounts-page.css"):
        css = (FOYER / "css" / name).read_text(encoding="utf-8")
        assert "touch-action: pan-y" in css, name


def test_foyer_pages_no_zoom():
    """壳自家三张门厅页 (登录/注册/账号) 也掐死放大缩小: meta 掐双击/聚焦
    放大, no-zoom.js 是 body 后第一条脚本 (2026-10-03 补齐, 与三应用同款)。"""
    for name in ("login", "register", "accounts"):
        html = (FOYER / f"{name}.html").read_text(encoding="utf-8")
        assert "maximum-scale=1, user-scalable=no" in html, name
        body_at = html.index("<body")
        assert html.index("<script", body_at + 1) == html.index(
            '<script src="/static/no-zoom.js?v=2"></script>'), name


def test_versioned_static_immutable():
    """带 ?v= 的静态请求回一年 immutable; 不带的 (manifest/图标) 照旧协商。"""
    client = TestClient(m.app)
    versioned = client.get("/static/menu-user.js?v=1")
    assert versioned.status_code == 200, versioned.text
    assert versioned.headers["cache-control"] == \
        "public, max-age=31536000, immutable"
    plain = client.get("/static/menu-user.js")
    assert plain.status_code == 200
    assert "immutable" not in plain.headers.get("cache-control", "")
