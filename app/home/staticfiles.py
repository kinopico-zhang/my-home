"""带版本查询串的静态资源回 immutable 缓存头 (?v= 家规的配套)。

2026-10-03 实锤: 静态资源没有 Cache-Control 只有启发式缓存, 手机过公网
(HTTPS/DDNS 高往返) 访问时每次导航浏览器都逐个再验证资产 —— 设置/统计
页点开慢的主因。页面引用一律带 ?v= 且内容一变必 bump 版本号 (家规),
带 v= 的请求放心回一年 immutable (零再验证); 不带 v= 的 (manifest/图标
这类没法换 URL 的) 照旧走 ETag 协商, 改了能及时生效。
"""
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

IMMUTABLE = "public, max-age=31536000, immutable"


def _versioned(scope: Scope) -> bool:
    """查询串带 v= 参数 (首参 ?v= 或后续 &v=) 才算版本化引用。"""
    query = scope.get("query_string", b"")
    return query.startswith(b"v=") or b"&v=" in query


class VersionedStaticFiles(StaticFiles):
    """?v= 请求 → 一年 immutable; 304 响应也带上 (缓存条目能升级)。"""

    async def get_response(self, path: str, scope: Scope) -> Response:
        """静态应答出来后再盖缓存头 (200 与 304 两条路都过这里)。"""
        response = await super().get_response(path, scope)
        if _versioned(scope):
            response.headers["Cache-Control"] = IMMUTABLE
        return response
