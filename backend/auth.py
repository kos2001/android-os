"""API 키 기반 인증·역할 (운영 인증 방식은 00-scope Q6 확정 후 교체).

인증 없이 동작하는 것은 명시적 개발 모드(ANDROID_OS_DEV_MODE=1)뿐이다. 개발 모드가 아니면
create_app 이 키 설정 누락을 시작 시점에 거부한다.

알려진 한계: 기기 키는 fleet 공유 키라 키 보유자는 device_hash 를 임의로 만들 수 있다(가짜 이벤트로
자동 halt 유발 가능). 기기별 인증(mTLS / Key Attestation) 도입 전까지 롤아웃 halt_rules.min_sample 을
충분히 크게 두고 이상 이벤트를 모니터링할 것.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel

ROLES = {"admin", "engineer", "release_manager", "operator", "pipeline", "viewer"}
DEV_PRINCIPAL_ACTOR = "dev"


class Principal(BaseModel):
    actor: str
    role: str


def parse_api_keys(raw: str) -> dict[str, Principal]:
    keys: dict[str, Principal] = {}
    for item in filter(None, (s.strip() for s in raw.split(","))):
        parts = item.split(":")
        if len(parts) != 3 or not all(p.strip() for p in parts):
            raise ValueError("ANDROID_OS_API_KEYS entries must be non-empty key:actor:role")
        key, actor, role = (p.strip() for p in parts)
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r} for actor {actor!r}")
        keys[key] = Principal(actor=actor, role=role)
    return keys


def parse_device_keys(raw: str) -> list[str]:
    return [k.strip() for k in raw.split(",") if k.strip()]


def _bearer(authorization: str | None) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


def _lookup(candidates, token: str):
    """상수 시간 비교로 일치하는 키를 찾는다."""
    found = None
    for key in candidates:
        if hmac.compare_digest(key.encode(), token.encode()):
            found = key
    return found


def require(*roles: str):
    allowed = set(roles) | {"admin"}

    def dependency(request: Request, authorization: str | None = Header(default=None)) -> Principal:
        keys: dict[str, Principal] = request.app.state.api_keys
        if not keys and request.app.state.dev_mode:
            return Principal(actor=DEV_PRINCIPAL_ACTOR, role="admin")
        token = _bearer(authorization)
        key = _lookup(keys, token) if token else None
        if key is None:
            raise HTTPException(401, "invalid or missing API key")
        principal = keys[key]
        if principal.role not in allowed:
            raise HTTPException(403, f"role {principal.role} not allowed")
        return principal

    return dependency


ANY = require("engineer", "release_manager", "operator", "pipeline", "viewer")
ENGINEER = require("engineer")
PIPELINE = require("pipeline", "release_manager")
RELEASE_MANAGER = require("release_manager")
OPERATOR = require("operator", "release_manager")


def require_device(request: Request, authorization: str | None = Header(default=None)) -> None:
    keys: list[str] = request.app.state.device_keys
    if not keys and request.app.state.dev_mode:
        return
    token = _bearer(authorization)
    if not token or _lookup(keys, token) is None:
        raise HTTPException(401, "invalid device credentials")
