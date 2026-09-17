"""记账同步测试: 离线优先 LWW / 墓碑 / 游标 / 记账人服务端盖章 / 跨库取名。

协议要点: id 客户端生成, 记账人 (created_by / updated_by) 服务端按会话落
(客户端说了不算), synced_at 是服务端时间作为增量游标, 删除是墓碑。
"""
from fastapi.testclient import TestClient

from app import account_store, config
import app.main as m


def _user(usersdb, name):
    """管理员直接建一个账号 + 登录态 client (不走邀请, 各用例独立)。"""
    account_store.ensure_admin(usersdb, config.AUTH_USER, config.AUTH_PASS)
    user = account_store.create_user(usersdb, name, "password123")
    client = TestClient(m.app)
    r = client.post("/api/login", json={"user": name, "password": "password123"})
    assert r.status_code == 200
    return client, user


def _entry(entry_id, updated_at, **kw):
    """一条上行账目 (客户端形状)。"""
    return {
        "id": entry_id, "date": "2026-09-13", "amount": 25.5,
        "kind": "expense", "category": "餐饮", "note": "午饭",
        "deleted": False, "updated_at": updated_at,
        **kw,
    }


def _sync(client, entries=(), last_sync=None):
    r = client.post("/bookkeeping/api/sync", json={
        "entries": list(entries), "last_sync": last_sync})
    assert r.status_code == 200, r.text
    return r.json()


def test_sync_stamps_identity_and_resolves_names(usersdb, bkdb):
    """记账人由服务端按会话落: 甲上传的账, 下行带甲的名字 (客户端没传也不算数)。"""
    jia, jia_user = _user(usersdb, "记账人甲")
    data = _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z")])
    assert len(data["entries"]) == 1
    out = data["entries"][0]
    assert out["created_by_name"] == "记账人甲"
    assert out["updated_by_name"] == "记账人甲"
    # 库里落的是甲的 uuid (跨库解析), 金额取两位
    from app.bookkeeping.store import Entry  # pylint: disable=import-outside-toplevel
    row = bkdb.get(Entry, "aaaa1111")
    assert row.created_by == jia_user.uuid
    assert row.amount == 25.5


def test_sync_lww_newer_wins_older_rejected(usersdb, bkdb):
    """同 id 再传: updated_at 更新才覆盖 (更新人换成上传者), 更旧不动。"""
    jia, _ = _user(usersdb, "记账人甲")
    yi, _ = _user(usersdb, "记账人乙")
    _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z", note="甲记的")])
    # 乙带着更旧版本同步: 不覆盖
    _sync(yi, [_entry("aaaa1111", "2026-09-13T07:00:00Z", note="乙的旧版")])
    data = _sync(yi)   # 全量拉 (last_sync 空)
    assert data["entries"][0]["note"] == "甲记的"
    # 乙带着更新版本: 覆盖, 更新人变乙
    _sync(yi, [_entry("aaaa1111", "2026-09-13T09:00:00Z", note="乙改的")])
    data = _sync(yi)
    out = [e for e in data["entries"] if e["id"] == "aaaa1111"][0]
    assert out["note"] == "乙改的"
    assert out["created_by_name"] == "记账人甲"      # 记账人不变
    assert out["updated_by_name"] == "记账人乙"      # 这版是乙改的


def test_sync_tombstone_not_hard_delete(usersdb, bkdb):
    """删除是墓碑: 行还在库里, 下行带 deleted=true。"""
    jia, _ = _user(usersdb, "记账人甲")
    _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z")])
    _sync(jia, [_entry("aaaa1111", "2026-09-13T09:00:00Z", deleted=True)])
    from app.bookkeeping.store import Entry  # pylint: disable=import-outside-toplevel
    assert bkdb.get(Entry, "aaaa1111") is not None      # 没被物理删
    data = _sync(jia)
    assert data["entries"][0]["deleted"] is True


def test_sync_cursor_incremental(usersdb):
    """游标 = 上次 server_now: 只下发这之后动的行 (别人的新账)。"""
    jia, _ = _user(usersdb, "记账人甲")
    yi, _ = _user(usersdb, "记账人乙")
    first = _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z")])
    # 乙首同步 (游标空): 全量, 拿到甲的账
    yi_first = _sync(yi)
    assert {e["id"] for e in yi_first["entries"]} == {"aaaa1111"}
    # 甲又记了一笔, 乙带着游标来: 只拿到新的这笔
    _sync(jia, [_entry("bbbb2222", "2026-09-13T09:00:00Z")],
          last_sync=first["server_now"])
    yi_second = _sync(yi, last_sync=yi_first["server_now"])
    assert {e["id"] for e in yi_second["entries"]} == {"bbbb2222"}


def test_sync_echoes_own_upload(usersdb):
    """上传后按游标再拉: 自己刚传的也在下行里 (回声), 客户端按 LWW 自合并。"""
    jia, _ = _user(usersdb, "记账人甲")
    first = _sync(jia)
    second = _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z")],
                   last_sync=first["server_now"])
    assert {e["id"] for e in second["entries"]} == {"aaaa1111"}


def test_sync_amount_rounding_and_ordering(usersdb):
    """金额取两位 (12.345 → 12.35); 下行按日期倒序。"""
    jia, _ = _user(usersdb, "记账人甲")
    _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z", amount=12.345),
                _entry("bbbb2222", "2026-09-12T08:00:00Z", amount=8)])
    data = _sync(jia)
    assert [e["id"] for e in data["entries"]] == ["aaaa1111", "bbbb2222"]
    assert data["entries"][0]["amount"] == 12.35


def test_sync_upload_limit(usersdb):
    """单次上行上限 1000 (防脏客户端灌爆): schema 层先拒 (422),
    bookkeeping_store.MAX_SYNC_UPLOAD 是第二道防线。"""
    jia, _ = _user(usersdb, "记账人甲")
    flood = [_entry(f"id{i:04d}", "2026-09-13T08:00:00Z") for i in range(1001)]
    r = jia.post("/bookkeeping/api/sync", json={"entries": flood})
    assert r.status_code == 422


def test_sync_input_validation(usersdb):
    """坏条目 422: 日期格式 / 金额非正 / kind 非法 / id 太短。"""
    jia, _ = _user(usersdb, "记账人甲")
    bad_cases = [
        _entry("aaaa1111", "2026-09-13T08:00:00Z", date="2026/09/13"),
        _entry("aaaa1111", "2026-09-13T08:00:00Z", amount=0),
        _entry("aaaa1111", "2026-09-13T08:00:00Z", amount=-5),
        _entry("aaaa1111", "2026-09-13T08:00:00Z", kind="transfer"),
        _entry("short", "2026-09-13T08:00:00Z"),
        _entry("aaaa1111", "2026-09-13T08:00:00Z", note="x" * 201),
    ]
    for i, entry in enumerate(bad_cases):
        r = jia.post("/bookkeeping/api/sync", json={"entries": [entry]})
        assert r.status_code == 422, f"case {i} 应被拒"


def test_sync_edit_propagates_to_other_user(usersdb):
    """端到端: 甲记 → 乙收 → 乙改 → 甲收到乙的版本 (记账人还是甲, 改的人是乙)。"""
    jia, _ = _user(usersdb, "记账人甲")
    yi, _ = _user(usersdb, "记账人乙")
    jia_first = _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z")])
    yi_first = _sync(yi)               # 乙首同步: 全量, 拿到甲的账
    got = yi_first["entries"][0]
    assert got["created_by_name"] == "记账人甲"
    _sync(yi, [_entry("aaaa1111", "2026-09-13T10:00:00Z",
                      amount=30, note="乙改的金额")],
          last_sync=yi_first["server_now"])
    jia_second = _sync(jia, last_sync=jia_first["server_now"])   # 甲用自己的游标
    out = [e for e in jia_second["entries"] if e["id"] == "aaaa1111"][0]
    assert out["amount"] == 30
    assert out["created_by_name"] == "记账人甲"
    assert out["updated_by_name"] == "记账人乙"


def test_sync_two_databases_separate(usersdb, tmp_path):
    """记账库与账号库是两个独立 SQLite 文件 (用户要求分开)。"""
    _user(usersdb, "记账人甲")
    users_file = tmp_path / "users.db"
    bookkeeping_file = tmp_path / "bookkeeping.db"
    assert users_file.exists() and bookkeeping_file.exists()
    assert users_file.read_bytes() != bookkeeping_file.read_bytes()


def test_sync_time_and_tags_roundtrip(usersdb, bkdb):
    """时刻 + 标签: 上行清洗 (去井号/空白, 去重, 截 12 字, 最多 5 个),
    落库逗号连接, 下行还原列表; 时刻格式错 422; 旧客户端不带字段也兼容。"""
    jia, _ = _user(usersdb, "记账人甲")
    data = _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z",
                              time="08:15",
                              tags=["#报销", "  固定  ", "报销",
                                    "十三字标签看会不会被截断掉", "x", "第六个"])])
    out = data["entries"][0]
    assert out["time"] == "08:15"
    assert out["tags"] == ["报销", "固定", "十三字标签看会不会被截断", "x", "第六个"]
    from app.bookkeeping.store import Entry  # pylint: disable=import-outside-toplevel
    row = bkdb.get(Entry, "aaaa1111")
    assert row.time == "08:15"
    assert row.tags == "报销,固定,十三字标签看会不会被截断,x,第六个"
    # 旧客户端 (再记功能前) 不带 time/tags: 默认空, 不报错
    data2 = _sync(jia, [_entry("bbbb2222", "2026-09-13T09:00:00Z")])
    plain = [e for e in data2["entries"] if e["id"] == "bbbb2222"][0]
    assert plain["time"] == "" and plain["tags"] == []
    # 时刻格式错: 422
    r = jia.post("/bookkeeping/api/sync", json={"entries": [
        _entry("cccc3333", "2026-09-13T08:00:00Z", time="8:15")]})
    assert r.status_code == 422


def test_migrate_columns_adds_time_and_tags(tmp_path):
    """老库升级: entries 已存在但没有 time/tags 列 → ALTER 补列, 旧行默认空;
    再跑一遍不炸不重复 (幂等)。"""
    from sqlalchemy import create_engine, text  # pylint: disable=import-outside-toplevel
    from app.bookkeeping import store  # pylint: disable=import-outside-toplevel
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as conn:          # v2.5 之前的老表 (无 time/tags)
        conn.execute(text(
            "CREATE TABLE entries (id VARCHAR PRIMARY KEY, date VARCHAR, "
            "amount FLOAT, kind VARCHAR, category VARCHAR, note VARCHAR, "
            "created_by VARCHAR, created_at DATETIME, updated_by VARCHAR, "
            "updated_at DATETIME, synced_at DATETIME, deleted BOOLEAN)"))
        conn.execute(text(
            "INSERT INTO entries VALUES ('old1', '2026-09-01', 12.0, "
            "'expense', '餐饮', '', 'u1', '2026-09-01 00:00:00', 'u1', "
            "'2026-09-01 00:00:00', '2026-09-01 00:00:00', 0)"))
    store.migrate_columns(eng)
    with eng.begin() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(entries)")]
        old_row = conn.execute(text(
            "SELECT time, tags FROM entries WHERE id = 'old1'")).one()
    assert "time" in cols and "tags" in cols
    assert old_row == ("", "")
    store.migrate_columns(eng)         # 幂等
    with eng.begin() as conn:
        cols2 = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(entries)")]
    assert cols2.count("time") == 1 and cols2.count("tags") == 1
    eng.dispose()


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
