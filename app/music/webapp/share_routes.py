"""My Music 的分享链接路由: 开链接 + 免登录的分享页全家桶。

/music/share/{token} 全家免登录 (主应用中间件放行该前缀): uuid 即凭证,
24 小时有效; 每个公开路由先验 token, 再验"要的东西确实在这份分享里"。
"""
from html import escape as escape_html

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from ... import database
from .. import (library_media, library_queries, library_settings,
                library_shares)
from ..library_database import get_db
from ..schemas import (LyricsResponse, ShareCreateRequest, ShareCreated,
                       SharePageData)
from .common import STATIC_DIR, _require_user

# 挂应用根: /share/{token} 本来就在根, /api/shares 用绝对路径搭车
router = APIRouter()


@router.post("/api/shares", response_model=ShareCreated)
def music_share_create(body: ShareCreateRequest, request: Request,
                       users: Session = Depends(database.get_users_db),
                       library: Session = Depends(get_db)) -> ShareCreated:
    """开一条分享链接 (歌/列表), 24 小时内任何人凭链接可看可听。"""
    user = _require_user(request, users)
    try:
        return library_shares.create_share(library, body.kind, body.id,
                                           user.uuid)
    except KeyError as exc:
        raise HTTPException(404, "分享的对象不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# share.html <head> 里的占位注释, 服务端换成 og: 标签 (微信卡片全靠它)
_OG_MARK = "<!--og-->"


def _share_og_tags(data: SharePageData | None, token: str,
                   base_url: str) -> str:
    """微信/QQ 分享卡片的 og: 三件套; 链接废了也给一套通用文案
    (占位符必须换掉, 不然卡片漏空)。"""
    if data is None:
        title, description = "My Music 分享", "链接不存在或已过期"
        image = f"{base_url}music/static/icon-512.png"
    else:
        title = data.title
        description = f"{data.subtitle} · My Music"
        image = _share_og_image(data, token, base_url)
    return (f'<meta property="og:title" content="{escape_html(title)}">\n'
            f'<meta property="og:description" content="{escape_html(description)}">\n'
            f'<meta property="og:image" content="{escape_html(image)}">')


def _share_og_image(data: SharePageData, token: str, base_url: str) -> str:
    """卡片缩略图 (绝对地址): 单曲 = 自己的内嵌图, 没有退专辑图;
    列表 = 自定义封面, 没传过退第一首的专辑图。"""
    def artwork_url(kind: str, item_id: int) -> str:
        """公开封面路由的绝对地址。"""
        return f"{base_url}music/share/{token}/artwork/{kind}/{item_id}"
    if data.kind == "track":
        track = data.tracks[0]
        if track.has_artwork:
            return artwork_url("track", track.track_id)
        return artwork_url("album", track.album_id)
    if data.playlist is not None and data.playlist.cover_version:
        return artwork_url("playlist", data.playlist.playlist_id)
    return artwork_url("album", data.tracks[0].album_id)


@router.get("/share/{token}")
def music_share_page(token: str, request: Request,
                     library: Session = Depends(get_db)) -> HTMLResponse:
    """分享页 (免登录): 谁点开都能看能听, 页面自己拉数据
    (路径里的 token 只是路由形状, 真校验在 api/stream/artwork 各路由)。

    服务端顺手把微信分享卡片要的 og: 三件套注进 <head> —— 微信不跑
    页面 JS, 卡片的标题/摘要/缩略图全看这里; 图片必须绝对地址。"""
    data = library_shares.share_page_data(library, token)
    markup = (STATIC_DIR / "share.html").read_text(encoding="utf-8")
    return HTMLResponse(
        markup.replace(_OG_MARK, _share_og_tags(data, token,
                                                str(request.base_url))),
        headers={"Cache-Control": "no-cache"})


@router.get("/share/{token}/api", response_model=SharePageData)
def music_share_data(token: str, response: Response,
                     library: Session = Depends(get_db)) -> SharePageData:
    """分享页的数据 (免登录): 歌/列表信息 + 曲目清单 + 失效时刻。"""
    response.headers["Cache-Control"] = "no-store"   # 过期与否必须现查
    data = library_shares.share_page_data(library, token)
    if data is None:
        raise HTTPException(410, "链接不存在或已过期")
    return data


@router.get("/share/{token}/stream/{track_id}")
def music_share_stream(token: str, track_id: int, request: Request,
                       library: Session = Depends(get_db)) -> Response:
    """分享页的音频流 (免登录, 支持 Range —— iOS Safari 必须)。"""
    scope = library_shares.share_scope(library, token)
    if scope is None:
        raise HTTPException(410, "链接不存在或已过期")
    if track_id not in scope.track_ids:
        raise HTTPException(404, "这首不在这份分享里")
    return library_media.stream_track(
        library, track_id, request.headers.get("range"))


@router.get("/share/{token}/artwork/{kind}/{item_id}")
def music_share_artwork(token: str, kind: str, item_id: int,
                        library: Session = Depends(get_db)) -> Response:
    """分享页的封面 (免登录): 曲目内嵌图 / 专辑封面 / 列表自定义封面,
    只放行这份分享里确实有的。"""
    scope = library_shares.share_scope(library, token)
    if scope is None:
        raise HTTPException(410, "链接不存在或已过期")
    if kind == "track" and item_id in scope.track_ids:
        return library_media.track_artwork_response(library, item_id)
    if kind == "album" and item_id in scope.album_ids:
        return library_media.album_artwork_response(library, item_id)
    if (kind == "playlist" and scope.kind == "playlist"
            and item_id == scope.playlist_id):
        return library_media.playlist_cover_response(library, item_id)
    raise HTTPException(404, "这张图不在这份分享里")


@router.get("/share/{token}/lyrics/{track_id}")
def music_share_lyrics(token: str, track_id: int,
                       library: Session = Depends(get_db)) -> LyricsResponse:
    """分享页的歌词 (免登录): 与应用内同一条取词通道 (库里没有且开着
    联网歌词时会顺手求一遍), 只放行这份分享里确实有的。"""
    scope = library_shares.share_scope(library, token)
    if scope is None:
        raise HTTPException(410, "链接不存在或已过期")
    if track_id not in scope.track_ids:
        raise HTTPException(404, "这首不在这份分享里")
    lyrics = library_queries.lyrics_for_track(
        library, track_id, library_settings.effective_lyrics_api(library))
    if lyrics is None:
        raise HTTPException(404, "曲目不存在")
    return lyrics
