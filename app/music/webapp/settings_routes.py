"""My Music 的设置与流量路由: 设置读写 (改是管理员专属) + 蜂窝流量月账。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ... import database
from ...schemas import OkResponse
from .. import library_settings, service
from ..library_database import get_db
from ..schemas import (CellularUsageReport, MusicSettingsState,
                       MusicSettingsUpdate)
from .common import _require_admin, _require_user

router = APIRouter(prefix="/api")


@router.get("/settings", response_model=MusicSettingsState)
def music_settings(request: Request,
                   users: Session = Depends(database.get_users_db),
                   library: Session = Depends(get_db)) -> MusicSettingsState:
    """设置页状态: 曲库路径 / 歌词 API 现值 + 蜂窝流量月账。

    谁登录都能看 (普通账号只读); 改要走 POST (管理员专属)。"""
    _require_user(request, users)
    return library_settings.settings_state(library)


@router.post("/settings", response_model=MusicSettingsState)
def music_settings_save(body: MusicSettingsUpdate, request: Request,
                        users: Session = Depends(database.get_users_db),
                        library: Session = Depends(get_db)) -> MusicSettingsState:
    """保存设置 (仅管理员); 曲库路径变了就同库换目录起全量重扫。"""
    _require_admin(request, users)
    try:
        new_directory = library_settings.save_settings(
            library, body.music_directory, body.lyrics_api_enabled,
            body.lyrics_api_base)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if new_directory is not None:
        service.apply_music_directory(new_directory)
    return library_settings.settings_state(library)


@router.post("/cellular-usage", response_model=OkResponse)
def music_cellular_usage(body: CellularUsageReport, request: Request,
                         users: Session = Depends(database.get_users_db),
                         library: Session = Depends(get_db)) -> OkResponse:
    """客户端报一笔蜂窝流量 (能认出蜂窝网络的浏览器定期上报, 记进当月账)。"""
    _require_user(request, users)
    library_settings.record_cellular_bytes(library, body.bytes)
    return OkResponse(ok=True)
