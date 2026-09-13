"""行程分组页测试: 页面骨架 + groups.js 交互片段 (CRUD 走 trips 的 api/groups,
已在 test_trips 覆盖; 这里只管新页面挂载)。"""


def test_groups_page_served(auth):
    """分组页: 列表骨架 (转圈/列表/空态/错误重试) + 页签菜单 + 轻提示。"""
    html = auth.get("/tesla/groups").text
    for frag in ['<h2>行程分组</h2>', 'id="count-badge"', 'id="gp-spin"',
                 'id="gp-list"', 'id="gp-empty"', 'id="errbox"', 'id="retry"',
                 'id="toast"', 'id="logout"', 'id="brand-menu"',
                 '<script src="/tesla/static/groups.js?v=1"></script>',
                 '在行程列表长按多选行程后点「存为分组」']:
        assert frag in html, f"分组页缺少 {frag}"
    # 页签菜单: 自己高亮, 行程页入口在 (分组管理搬来这, 行程页只留创建)
    assert '<a class="on" href="/tesla/groups">行程分组</a>' in html
    assert 'href="/tesla/trips"' in html


def test_groups_page_interactions(auth):
    """分组页脚本: 打开跳行程页深链合并播放, 改名行内编辑, 删除二次确认。
    行内重渲染会脱链事件目标 —— 委托先判 isConnected (与行程页同一坑)。"""
    js = auth.get("/tesla/static/groups.js?v=1").text
    for frag in ['"/tesla/trips/api/groups"', "function rowHTML(",
                 "function render()", "async function load()",
                 '"/tesla/trips?ids=" + item.dataset.ids',
                 'classList.add("arm")', "确认删除",
                 'method: "DELETE"', 'method: "PATCH"',
                 'gp-list").addEventListener("click"',
                 'gp-list").addEventListener("keydown"',
                 "!t.isConnected", 'status === 401',
                 'class="gp-input"', 'maxlength="30"']:
        assert frag in js, f"groups.js 缺少 {frag}"
    # 改名/删除按钮有结果才动列表; Enter 提交 / Esc 放弃
    assert 'e.target.classList.contains("gp-input")' in js
    assert 'e.key === "Enter"' in js and 'e.key === "Escape"' in js
