"""My Music 静态资源读取夹具。

2026-09-17 结构化重构 (用户令: 文件 ≤200 行按逻辑拆分, html/css/js 分家):
music.js / music-player.js 按逻辑拆进 js/ 的见名知意小文件, 内联
<style> 拆进 css/, 页面按引用加载。静态文本断言要保持整页口径, 这里
把页面引用的资源按序拼回等价视图:

- music_page_shell(): markup + css (按 link 序) —— 等价拆分前带内联样式的 html 全文
- music_browser_js(): 浏览页模块 (原 music.js, music-*.js 去掉播放器组与公共件)
- music_player_js():  播放器模块 (原 music-player.js, music-player-*.js)
- share_page_shell() / share_page_js(): 分享页同款
- page_script_paths(page): 页面引用的脚本路径清单 (结构断言用)
"""
import re
from collections.abc import Iterable
from pathlib import Path

MUSIC_STATIC = Path(__file__).resolve().parent.parent / "app" / "music" / "static"


def _refs(page: str, pattern: str) -> tuple[str, list[Path]]:
    """页面里按出现序引用的静态资源路径 (剥掉 /music/static 前缀与版本参数)。"""
    html = (MUSIC_STATIC / page).read_text(encoding="utf-8")
    paths = [MUSIC_STATIC / src.split("/music/static/")[1].split("?")[0]
             for src in re.findall(pattern, html)]
    return html, paths


def _cat(paths: Iterable[Path]) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in paths)


def music_page_shell() -> str:
    """music.html markup + 全部 css —— 拆分前 <style> 内联时代的整页口径。"""
    html, css_paths = _refs("music.html", r'<link rel="stylesheet" href="([^"]+)"')
    return html + "\n" + _cat(css_paths)


def music_browser_js() -> str:
    """浏览页模块 (原 music.js 口径): js/music-*.js, 排除播放器组与公共小件。"""
    return _cat(p for p in page_script_paths("music.html")
                if p.parent.name == "js" and p.name.startswith("music-")
                and not p.name.startswith("music-player-")
                and p.name != "music-common.js")


def music_player_js() -> str:
    """播放器模块 (原 music-player.js 口径): js/music-player-*.js 按加载序。"""
    return _cat(p for p in page_script_paths("music.html")
                if p.name.startswith("music-player-"))


def share_page_shell() -> str:
    """share.html markup + css —— 拆分前的整页口径。"""
    html, css_paths = _refs("share.html", r'<link rel="stylesheet" href="([^"]+)"')
    return html + "\n" + _cat(css_paths)


def share_page_js() -> str:
    """share.html 引用的全部脚本 (lyrics-parser + js/share/), 按加载序。"""
    return _cat(page_script_paths("share.html"))


def page_script_paths(page: str):
    """页面 <script src> 引用的脚本路径清单 (按出现序)。"""
    return _refs(page, r'<script src="([^"]+)"')[1]
