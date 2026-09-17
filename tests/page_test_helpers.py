"""页面测试共享助手: 全站页面清单 + html/css 拼接口径。
拆自 test_auth.py (结构化重构, 代码逐字节未动)。"""
import re

from fastapi.testclient import TestClient

ALL_PAGES = ["/", "/login", "/register", "/tesla/charging", "/tesla/stats",
             "/tesla/chargemap", "/tesla/map", "/tesla/changelog", "/tesla/trips",
             "/tesla/groups", "/tesla/live", "/tesla/settings", "/accounts",
             "/bookkeeping", "/music"]


def _page_with_css(client: TestClient, path: str) -> str:
    """页面 HTML + 其引用的样式表拼起来 (2026-09-17 结构化重构后 CSS 拆出
    html 进独立文件, "整页" 断言的口径 = markup + 引用的 css)。"""
    html: str = client.get(path).text
    refs = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    css = "".join(client.get(href).text for href in refs)
    return html + css
