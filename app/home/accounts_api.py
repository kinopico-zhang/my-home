"""账号管理接口 (/accounts/api/*, 仅管理员): 用户列表 + 邀请签发/列表/撤销。

页面在 /accounts (pages.py); uuid 全程不出接口。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import account_store, config, database
from ..schemas import (
    InvitationCreated,
    InvitationItem,
    InvitationRequest,
    OkResponse,
    UserItem,
)
from .session_api import _require_admin

accounts = APIRouter(prefix="/accounts/api")


def to_local(dt: datetime) -> datetime:
    """库内 UTC 裸时间戳 → 本地时间 (默认北京时间)。

    拆仓前住在 tesla.repository (Tesla 侧的时间助手), 现在 tesla 在子仓里
    (合成包名), 共享层自带一份同配方的, 不跨仓引用。"""
    return dt.replace(tzinfo=timezone.utc).astimezone(config.LOCAL_TZ)


@accounts.get("/users", response_model=list[UserItem])
def accounts_list_users(request: Request,
                        users: Session = Depends(database.get_users_db)) -> list[UserItem]:
    """账号列表 (仅管理员; uuid 不出接口)。"""
    _require_admin(request, users)
    return [UserItem(name=u.name, is_admin=u.is_admin,
                     created_at=to_local(u.created_at))
            for u in account_store.list_users(users)]


@accounts.post("/invitations", response_model=InvitationCreated)
def accounts_create_invitation(body: InvitationRequest, request: Request,
                               users: Session = Depends(database.get_users_db)
                               ) -> InvitationCreated:
    """签发注册邀请 (仅管理员; 前端拼 /register?invite= 链接分享)。"""
    _require_admin(request, users)
    try:
        invitation = account_store.create_invitation(users, body.days)
    except account_store.InvitationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return InvitationCreated(token=invitation.token,
                             expires_at=to_local(invitation.expires_at))


@accounts.get("/invitations", response_model=list[InvitationItem])
def accounts_list_invitations(request: Request,
                              users: Session = Depends(database.get_users_db)
                              ) -> list[InvitationItem]:
    """邀请列表 (仅管理员, 签发时间倒序)。"""
    _require_admin(request, users)
    return [InvitationItem(token=i.token, created_at=to_local(i.created_at),
                           expires_at=to_local(i.expires_at),
                           used_at=to_local(i.used_at) if i.used_at else None,
                           revoked=i.revoked)
            for i in account_store.list_invitations(users)]


@accounts.delete("/invitations/{token}", response_model=OkResponse)
def accounts_revoke_invitation(token: str, request: Request,
                               users: Session = Depends(database.get_users_db)) -> OkResponse:
    """撤销未使用的邀请 (仅管理员)。"""
    _require_admin(request, users)
    if not account_store.revoke_invitation(users, token):
        raise HTTPException(400, "邀请不存在或已被使用")
    return OkResponse(ok=True)
