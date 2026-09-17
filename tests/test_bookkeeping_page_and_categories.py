"""记账类别与页面测试: 挖财种子导入, 类别树端点, 金额键盘,
计算器接线。
拆自 test_bookkeeping.py (结构化重构, 代码逐字节未动)。"""
from fastapi.testclient import TestClient

import app.main as m
from tests.bookkeeping_sync_helpers import _user

# ---------------------------------------------------------------- 类别 (挖财导入)

def test_categories_seeded_from_wacai(usersdb, bkdb):
    """类别树种子: 空库建好就有 (挖财导出的 163 类), 大类在前子类随后。"""
    from app.bookkeeping import store  # pylint: disable=import-outside-toplevel
    tree = store.category_tree(bkdb)
    assert len(tree.expense) == 14           # 支出大类
    assert len(tree.income) == 15            # 收入大类
    canyin = tree.expense[0]
    assert canyin.name == "餐饮"
    assert "早餐" in canyin.children and "餐饮其他" in canyin.children
    income_names = [group.name for group in tree.income]
    assert "工资薪水" in income_names and "顺风车" in income_names
    # 子类总数对上 (大类的子类拼起来)
    assert sum(len(group.children) for group in tree.expense) == 134
    assert all(group.children == [] for group in tree.income)


def test_categories_seeded_only_once(usersdb, bkdb):
    """非空不重种: 再跑一次种子 (幂等), 行数不长。"""
    from sqlalchemy import func, select  # pylint: disable=import-outside-toplevel
    from app.bookkeeping import store  # pylint: disable=import-outside-toplevel
    store.seed_default_categories()
    store.seed_default_categories()
    count = bkdb.execute(
        select(func.count()).select_from(store.Category)).scalar_one()
    assert count == 163


def test_categories_api_serves_tree(usersdb):
    """GET /bookkeeping/api/categories: 登录可拿两级树, 形状给前端画胶囊。"""
    client, _ = _user(usersdb, "记账人甲")
    r = client.get("/bookkeeping/api/categories")
    assert r.status_code == 200, r.text
    tree = r.json()
    tops = {g["name"]: g["children"] for g in tree["expense"]}
    assert tops["交通"][0] == "充电"          # 子类有序 (种子顺序)
    assert "房贷" in tops and tops["房贷"] == []
    assert any(g["name"] == "工资薪水" for g in tree["income"])


def test_categories_api_requires_login(usersdb):
    """类别接口也是登录态资源: 未登录 401。"""
    anon = TestClient(m.app)
    assert anon.get("/bookkeeping/api/categories").status_code == 401


def test_bookkeeping_page_has_amount_keyboard():
    """金额键盘 (紧凑): 右列 ⌫/完成 两枚大键, 无再记键, 无独立保存按钮;
    小类直接铺图标格子 (子类行没了); 时间/标签字段; 把手下拉关闭;
    图标 emoji 单色化; 纯逻辑脚本单独成文件。"""
    from pathlib import Path  # pylint: disable=import-outside-toplevel
    base = Path(__file__).parent.parent / "app" / "bookkeeping" / "static"
    html = (base / "bookkeeping.html").read_text(encoding="utf-8")
    # 样式拆去了 css/ (结构化重构), 断言拼齐 html + 全部 css 文件
    css = "".join(p.read_text(encoding="utf-8")
                  for p in sorted((base / "css").glob("*.css")))
    assert 'id="f-amount" type="text" inputmode="none"' in html
    assert 'id="amt-pad"' in html and 'id="amt-eq"' in html
    assert 'class="cat-tiles" id="cat-tiles"' in html
    assert 'id="cat-sub"' not in html and 'cat-sub' not in css  # 子类上格后子类行整个撤掉
    for k in ("back", "done", "7", "8", "9", "/", "4", "5",
              "6", "*", "1", "2", "3", "-", "0", ".", "+"):
        assert f'data-k="{k}"' in html, f"键盘缺键 {k}"
    assert 'data-k="again"' not in html           # 再记键撤了 (完成一记到底)
    assert 'data-k="clear"' not in html          # 清空改长按 ⌫
    assert 'id="sheet-save"' not in html         # 保存并进键盘 (完成)
    assert 'id="sheet-close"' in html and 'id="sheet-del"' in html
    assert 'position: sticky; bottom: 0' in css   # 键盘吸底常驻
    assert 'id="f-time" type="time"' in html       # 记账时刻
    assert 'id="f-tags"' in html and 'id="tag-chips"' in html   # 标签 + 历史胶囊
    assert 'id="grab-zone"' in html and 'touch-action: none' in css  # 把手下拉关闭
    assert 'filter: grayscale(1)' in css          # 类别图标单色化
    assert 'max-height: 34dvh' in css             # 格子区限高自滚, 弹层一屏放下
    assert 'src="/bookkeeping/static/amount-calculator.js?v=1"' in html


def test_bookkeeping_js_wires_calculator_and_categories():
    """接线: 完成走 saveEntry (evaluateAmount 求值, 不再 parseFloat), ⌫ 走
    pointerdown (长按清空), 类别树服务器拿 + 缓存本地 (小类直接上格, 子类行
    撤了), 时间/标签进条目, 把手 window 级 pointer 下拉关闭。"""
    from pathlib import Path  # pylint: disable=import-outside-toplevel
    base = Path(__file__).parent.parent / "app" / "bookkeeping" / "static"
    # 大脚本按逻辑拆成了 bookkeeping-*.js 多个模块 (结构化重构), 断言按
    # bookkeeping.html 里的加载顺序拼接起来整体查
    modules = ("bookkeeping-merge", "amount-calculator", "bookkeeping-state",
               "bookkeeping-render", "bookkeeping-sync", "bookkeeping-entry-sheet",
               "bookkeeping-amount-pad", "bookkeeping-boot")
    js = "".join((base / f"{name}.js").read_text(encoding="utf-8")
                 for name in modules)
    assert "evaluateAmount($(\"#f-amount\").value)" in js
    assert "applyAmountKey(input.value, btn.dataset.k)" in js
    assert "parseFloat($(\"#f-amount\").value)" not in js
    assert 'btn.dataset.k === "done"' in js
    assert "again" not in js                       # 再记整个撤了
    assert "function saveEntry()" in js
    assert '"pointerdown"' in js and '"clear"' in js   # 长按 ⌫ 清空
    assert '"/bookkeeping/api/categories"' in js
    assert 'saveLS("bk-categories-v2"' in js \
        and 'loadLS("bk-categories-v2"' in js   # v2: 类别树换成 pydantic 形状
    assert "#cat-tiles" in js and "treeFor(sheetKind)" in js
    assert "cat-sub" not in js                     # 子类行撤了
    assert "function parseTags(" in js and "function nowTime(" in js
    assert "function renderTagChips()" in js       # 标签历史胶囊
    assert 'time: e.time || ""' in js and "tags: e.tags || []" in js  # 同步映射
    assert '$("#grab-zone")' in js and "translateY(${dy}px)" in js    # 把手拖动
    assert "CATEGORY_ICONS" in js and "CATEGORIES" not in js
