"""My Music 的路由层 —— 独立小应用, 挂在主应用的 /music 下。

本文件是组装点: 各资源域 (页面会话 / 分享 / 曲库浏览 / 播放列表 /
设置 / 媒体流) 各住一个 routes 文件, 公共底座 (应用实例 / 鉴权助手)
在 common.py。与 My Tesla 只共享账号体系: 同一枚会话 cookie + 账号库
(users.db)。JSON 接口在 /music/api (主应用中间件统一 no-store), 媒体流
在 /music/media (自带长缓存头: 封面带版本号可 immutable)。
"""
from .common import music_app
from . import (library_routes, media_routes, page_routes, playlist_routes,
               settings_routes, share_routes)

music_app.include_router(page_routes.router)      # / /login /sw.js /changelog
music_app.include_router(page_routes.api_router)  # /api/logout
music_app.include_router(share_routes.router)     # /api/shares + /share/{token}*
music_app.include_router(library_routes.router)   # /api: 曲库浏览与查询
music_app.include_router(settings_routes.router)  # /api: 设置 + 蜂窝流量
music_app.include_router(playlist_routes.router)  # /api: 播放列表
music_app.include_router(media_routes.router)     # /media: 音频流与封面

__all__ = ["music_app"]
