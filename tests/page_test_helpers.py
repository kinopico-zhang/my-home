"""页面测试共享助手: 全站页面清单 + html/css 拼接口径。
根路径已撤门厅 (302 进 /music), 不算页面; 清单只列真页面。"""
import re

from fastapi.testclient import TestClient

import app.main as m

ALL_PAGES = ["/login", "/register", "/tesla/charging", "/tesla/stats",
             "/tesla/chargemap", "/tesla/map", "/tesla/changelog", "/tesla/trips",
             "/tesla/groups", "/tesla/live", "/tesla/settings", "/accounts",
             "/bookkeeping", "/music"]

# 公开页: 已登录的访客会被 302 进默认应用, 断言要用匿名视角取
PUBLIC_PAGES = ("/login", "/register")


def _page_client(auth: TestClient, path: str) -> TestClient:
    """取某页面的合适视角: 公开页新开匿名 client, 业务页用已登录的。"""
    return TestClient(m.app) if path in PUBLIC_PAGES else auth


def _page_with_css(client: TestClient, path: str) -> str:
    """页面 HTML + 其引用的样式表拼起来 (2026-09-17 结构化重构后 CSS 拆出
    html 进独立文件, "整页" 断言的口径 = markup + 引用的 css)。"""
    html: str = _page_client(client, path).get(path).text
    refs = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    css = "".join(client.get(href).text for href in refs)
    return html + css
