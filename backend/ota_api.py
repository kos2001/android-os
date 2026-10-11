"""OTA Delivery API — P2 패키지 등록 · P3 기기 update-check/events · P4 롤아웃 운영.

Device API (/device/v1, ANDROID_OS_DEVICE_KEYS):
  POST /device/v1/update-check
  POST /device/v1/events
Admin API (/admin/v1):
  POST /packages {url, sha256?}           원격 OTA zip 검사 → 등록(ready|rejected)
  POST /packages/inspect {url}            등록 없이 검사
  GET  /packages?device= · /packages/{id} · POST /packages/{id}/retire
  POST /rollouts · GET /rollouts · GET /rollouts/{id}
  POST /rollouts/{id}/{start|promote|pause|resume|halt|complete}
  GET  /rollouts/{id}/metrics · POST /rollouts/{id}/evaluate-halt
  GET  /reports/delta-candidates?target_fingerprint=&days=
"""
from __future__ import annotations

import ipaddress
import logging
import random
import socket
import threading
from dataclasses import asdict, replace
from datetime import datetime
from typing import Annotated, Callable, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Query
from pydantic import BaseModel, Field

from upgrade_core.matcher import DeviceState, Match, filters_match, select_update
from upgrade_core.ota_package import OtaPackageError, inspect_ota_package
from upgrade_core.remote import HttpRangeFile, RangeNotSupported, RedirectRefused
from upgrade_core.rollout import ERROR_NAMES, evaluate_halt

from .auth import ANY, OPERATOR, PIPELINE, RELEASE_MANAGER, Principal, require_device
from .ota_store import IN_PROGRESS_STATES, RETRYABLE_STATES, OtaStore
from .store import Conflict

log = logging.getLogger("android_os.ota")
DEFAULT_CHECK_INTERVAL_S = 6 * 3600
SCATTER = 0.1
SHA256_HEX = r"^[0-9a-f]{64}$"
AUTO_HALT_ACTOR = "auto-halt"
# 재부팅 여부 판정용 (/proc/sys/kernel/random/boot_id)
BOOT_ID = r"^[0-9a-fA-F-]{8,64}$"
Tag = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,31}$")]


class DeviceTagsIn(BaseModel):
    tags: list[Tag] = Field(max_length=20)


# --------------------------------------------------------------------------- #
# 모델
# --------------------------------------------------------------------------- #
class LastUpdate(BaseModel):
    assignment_id: int | None = None
    status: int | None = None
    error_code: int | None = None


class UpdateCheckIn(BaseModel):
    device: str = Field(min_length=1, max_length=64)
    fingerprint: str = Field(min_length=1, max_length=256)
    incremental: str | None = None
    build_timestamp: int = Field(ge=0)
    security_patch: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    sdk_level: int | None = None
    slot_suffix: str | None = None
    boot_id: str | None = Field(default=None, pattern=BOOT_ID)
    channel: Literal["testing", "beta", "stable"] = "stable"
    carrier: str | None = None
    region: str | None = None
    sku: str | None = None
    device_hash: str = Field(pattern=SHA256_HEX)
    last_update: LastUpdate | None = None
    conditions: dict = Field(default_factory=dict)


class DeviceEvent(BaseModel):
    assignment_id: int | None = None
    attempt: int | None = Field(default=None, ge=1)
    type: Literal["download_started", "status", "error", "updated_need_reboot"]
    update_status: int | None = Field(default=None, ge=0, le=9)
    progress: float | None = Field(default=None, ge=0, le=1)
    error_code: int | None = Field(default=None, ge=-(2**31), le=2**32 - 1)
    boot_id: str | None = Field(default=None, pattern=BOOT_ID)
    fingerprint: str | None = None
    occurred_at: datetime


class EventsIn(BaseModel):
    device_hash: str = Field(pattern=SHA256_HEX)
    events: list[DeviceEvent] = Field(min_length=1, max_length=100)


class PackageIn(BaseModel):
    url: str
    sha256: str | None = Field(default=None, pattern=SHA256_HEX)


class InspectIn(BaseModel):
    url: str


class StageIn(BaseModel):
    percent: float = Field(gt=0, le=100)
    min_soak_hours: float = Field(default=24, ge=0)
    min_successful_boots: int = Field(default=0, ge=0)
    min_success_rate: float | None = Field(default=None, ge=0, le=1)


class RolloutFilters(BaseModel):
    carriers: list[str] | None = None
    regions: list[str] | None = None
    skus: list[str] | None = None
    source_fingerprints: list[str] | None = None
    tags: list[Tag] | None = Field(default=None, max_length=20)


class HaltRules(BaseModel):
    min_sample: int = Field(default=100, ge=1)
    max_error_rate: float | None = Field(default=None, ge=0, le=1)
    max_boot_fallback_rate: float | None = Field(default=None, ge=0, le=1)
    max_error_code_rate: dict[Annotated[str, Field(pattern=r"^\d+$")], Annotated[float, Field(ge=0, le=1)]] = \
        Field(default_factory=dict)
    window_minutes: int | None = Field(default=None, ge=1)


class Policy(BaseModel):
    require_unmetered: bool = True
    min_battery_pct: int = Field(default=30, ge=0, le=100)
    install_window: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$")
    switch_slot_on_reboot: bool = True
    mandatory: bool = False
    check_interval_s: int = Field(default=DEFAULT_CHECK_INTERVAL_S, ge=300)
    max_attempts: int = Field(default=2, ge=1, le=10)


class RolloutIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    target_fingerprint: str
    channel: Literal["testing", "beta", "stable"]
    stages: list[StageIn] = Field(min_length=1, max_length=20)
    filters: RolloutFilters = Field(default_factory=RolloutFilters)
    halt_rules: HaltRules = Field(default_factory=HaltRules)
    halt_mode: Literal["stop_new", "stop_all_pending"] = "stop_new"
    policy: Policy = Field(default_factory=Policy)


class ReasonIn(BaseModel):
    reason: str | None = None


# --------------------------------------------------------------------------- #
# 패키지 읽기 (SSRF 방지: https, 호스트 allowlist, 공인 IP, 리다이렉트 거부)
# --------------------------------------------------------------------------- #
PackageOpener = Callable[[str], object]


def _resolves_to_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    return bool(infos) and all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


def https_range_opener(allowed_hosts: set[str], restrict: bool = True) -> PackageOpener:
    """restrict=False(개발 모드)면 호스트 allowlist·공인 IP 검사를 생략한다. https·리다이렉트 거부는 항상 적용."""
    def open_package(url: str):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise HTTPException(422, "only https URLs are accepted")
        if restrict:
            if parsed.hostname not in allowed_hosts:
                raise HTTPException(403, f"host {parsed.hostname} not in ANDROID_OS_PACKAGE_HOSTS")
            if not _resolves_to_public(parsed.hostname):
                raise HTTPException(403, f"host {parsed.hostname} does not resolve to a public address")
        return HttpRangeFile(url, block_size=1 << 18)

    return open_package


def _inspect(request: Request, url: str):
    try:
        fp = request.app.state.package_opener(url)
        return fp, inspect_ota_package(fp, compute_sha256=False)
    except RangeNotSupported as exc:
        raise HTTPException(422, f"origin must support HTTP Range: {exc}") from exc
    except RedirectRefused as exc:
        raise HTTPException(422, "origin redirected; register the final URL") from exc
    except OtaPackageError as exc:
        raise HTTPException(422, f"not a valid OTA package: {exc}") from exc
    except (OSError, ValueError) as exc:
        log.warning("package read failed for %s: %s", url, exc)
        raise HTTPException(502, "failed to read package from origin") from exc


# --------------------------------------------------------------------------- #
# update-check 조립
# --------------------------------------------------------------------------- #
PAYLOAD_KEYS = ("FILE_HASH", "FILE_SIZE", "METADATA_HASH", "METADATA_SIZE")


def apply_payload_headers(pkg: dict, policy: dict) -> list[str]:
    """UpdateEngine.applyPayload headerKeyValuePairs.

    불리언 헤더는 update_attempter_android.cc GetHeaderAsBool 기준으로 "0"/"1" 만 유효하다
    (그 외 값은 기본값: POWERWASH=false, SWITCH_SLOT_ON_REBOOT=true). 기본값과 다를 때만 넣는다.
    """
    props = pkg["payload_properties"]
    headers = [f"{k}={props[k]}" for k in PAYLOAD_KEYS]
    if pkg["wipe"]:
        headers.append("POWERWASH=1")
    if pkg["spl_downgrade"]:
        headers.append("SPL_DOWNGRADE=1")
    if not policy.get("switch_slot_on_reboot", True):
        headers.append("SWITCH_SLOT_ON_REBOOT=0")
    return headers


def _next_check(policy: dict) -> int:
    base = policy.get("check_interval_s", DEFAULT_CHECK_INTERVAL_S)
    return int(base * random.uniform(1 - SCATTER, 1 + SCATTER))


def _offer_decision(ota: OtaStore, dev: DeviceState, candidates: list[dict], existing: dict) -> Match | dict:
    """Pure offer selection shared by real checks and inventory previews."""
    # 진행 중인 할당이 있는 롤아웃을 먼저 본다 (새 롤아웃이 생겨도 설치 중인 업데이트를 유지)
    def priority(r: dict) -> int:
        a = existing.get(r["id"])
        return 0 if a and a["state"] in IN_PROGRESS_STATES else 1

    matchers = []
    for r in sorted(candidates, key=priority):
        a = existing.get(r["id"])
        in_progress = a is not None and a["state"] in IN_PROGRESS_STATES
        continued = in_progress and (r["state"] in ("active", "paused") or
                                    (r["state"] == "halted" and r["halt_mode"] == "stop_new"))
        matcher = ota.to_matcher(r, percent_override=100 if continued else None,
                                 state_override="active" if continued else None)
        if continued:
            matcher = replace(matcher, filters={k: v for k, v in matcher.filters.items() if k != "tags"})
        matchers.append(matcher)
    result = select_update(matchers, dev)
    if not isinstance(result, Match):
        filtered = bool(matchers) and not any(filters_match(r, dev) for r in matchers)
        return {"update_available": False, "reason": "FILTER_MISMATCH" if filtered else result.reason}
    rollout = next(r for r in candidates if r["id"] == result.rollout.id)
    previous = existing.get(rollout["id"])
    if previous and previous["state"] == "installed_pending_reboot" and previous["package_id"] == result.package.id:
        # 설치 완료·재부팅 대기: 같은 패키지를 다시 내려주면 재설치 루프가 된다
        return {"update_available": False, "reason": "PENDING_REBOOT", "assignment_id": previous["id"],
                "attempt": previous["attempt"], "_rollout_id": rollout["id"]}
    max_attempts = rollout["policy"].get("max_attempts", 2)
    if previous and previous["state"] in RETRYABLE_STATES and previous["attempt"] >= max_attempts:
        return {"update_available": False, "reason": "RETRY_LIMIT_REACHED", "_rollout_id": rollout["id"]}
    return result


def update_check(ota: OtaStore, body: UpdateCheckIn) -> dict:
    ota.record_check(body.device_hash, body.device, body.fingerprint, body.model_dump(exclude={"device_hash"}))
    ota.apply_boot_outcomes(body.device_hash, body.fingerprint, body.boot_id)
    candidates = ota.candidate_rollouts(body.device, body.channel)
    existing = {a["rollout_id"]: a for a in ota.assignments_for(body.device_hash)}
    dev = DeviceState(device=body.device, fingerprint=body.fingerprint, build_timestamp=body.build_timestamp,
                      security_patch=body.security_patch, channel=body.channel, device_hash=body.device_hash,
                      carrier=body.carrier, region=body.region, sku=body.sku, tags=ota.device_tags(body.device_hash))
    result = _offer_decision(ota, dev, candidates, existing)
    if not isinstance(result, Match):
        policy = candidates[0]["policy"] if candidates else {}
        selected_id = result.pop("_rollout_id", None)
        if selected_id is not None:
            policy = next(r["policy"] for r in candidates if r["id"] == selected_id)
        return {**result, "next_check_after_s": _next_check(policy)}
    rollout = next(r for r in candidates if r["id"] == result.rollout.id)
    pkg = next(p for p in rollout["packages"] if p["id"] == result.package.id)
    assignment = ota.upsert_assignment(rollout["id"], body.device_hash, pkg["id"], body.fingerprint)
    target = ota.build_by_fingerprint(rollout["target_fingerprint"])
    props = pkg["payload_properties"]
    return {
        "update_available": True,
        "assignment_id": assignment["id"],
        "attempt": assignment["attempt"],
        "rollout": {"id": rollout["id"], "name": rollout["name"]},
        "target": {"fingerprint": target["fingerprint"], "incremental": target["incremental"],
                   "sdk_level": target["sdk_level"], "security_patch": target["spl"]},
        "package": {
            "id": pkg["id"], "type": pkg["type"], "wipe": pkg["wipe"], "url": pkg["url"],
            "file_size": pkg["file_size"], "sha256": pkg["sha256"],
            "payload_offset": pkg["payload_offset"], "payload_size": pkg["payload_size"],
            "payload_metadata": pkg["payload_metadata"],
            "streaming_property_files": pkg["streaming_property_files"],
            "headers": apply_payload_headers(pkg, rollout["policy"]),
        },
        "policy": {k: v for k, v in rollout["policy"].items() if k not in ("check_interval_s", "max_attempts")},
        "next_check_after_s": _next_check(rollout["policy"]),
    }


def preview_rollout(ota: OtaStore, rid: int) -> dict:
    """Read-only snapshot for one rollout. Drafts simulate their first stage."""
    with ota.s.tx():
        r = ota.rollout_with_packages(rid)
        draft = r["state"] == "draft"
        if draft:
            r = {**r, "state": "active", "current_percent": r["stages"][0]["percent"]}
        assignments = {a["device_hash"]: a for a in ota.s._all(
            "SELECT * FROM assignment WHERE rollout_id = ?", (rid,))}
        reasons, packages, sample = {}, {"full": 0, "incremental": 0}, []
        total = eligible = 0
        cursor = ""
        while True:
            rows = ota.s._all("SELECT * FROM fleet_device WHERE device = ? AND channel = ? "
                              "AND device_hash > ? ORDER BY device_hash LIMIT 200", (r["device"], r["channel"], cursor))
            if not rows:
                break
            cursor = rows[-1]["device_hash"]
            for row in ota._inventory_out(rows):
                total += 1
                dev = DeviceState(**{k: row[k] for k in (
                    "device", "fingerprint", "build_timestamp", "security_patch", "channel", "device_hash",
                    "carrier", "region", "sku")}, tags=tuple(row["tags"]))
                assignment = assignments.get(dev.device_hash)
                result = _offer_decision(ota, dev, [r], {rid: assignment} if assignment else {})
                if isinstance(result, Match):
                    eligible += 1
                    packages[result.package.type] += 1
                    reason = "ELIGIBLE"
                else:
                    reason = result["reason"]
                    if reason == "UP_TO_DATE" and r["state"] in ("paused", "completed") and dev.fingerprint != r["target_fingerprint"]:
                        reason = "ROLLOUT_INACTIVE"
                reasons[reason] = reasons.get(reason, 0) + 1
                if len(sample) < 20:
                    sample.append({"device_hash": dev.device_hash, "reason": reason})
        return {"rollout_id": rid, "mode": "draft_first_stage" if draft else "current_stage",
                "percent": r["current_percent"], "total": total, "eligible": eligible,
                "reasons": reasons, "packages": packages, "sample": sample, "as_of": datetime.now().astimezone().isoformat()}


# --------------------------------------------------------------------------- #
# 자동 halt
# --------------------------------------------------------------------------- #
def evaluate_rollout(ota: OtaStore, rid: int, apply: bool, actor: str = AUTO_HALT_ACTOR) -> dict:
    r = ota.get_rollout(rid)
    rules = {k: v for k, v in r["halt_rules"].items() if v is not None}
    window = ota.rollout_window(rid, rules.get("window_minutes"))
    decision = evaluate_halt(window, rules)
    halted = False
    if decision.halt and apply and r["state"] in ("active", "paused"):
        try:
            ota.transition(rid, "halt", actor, reason="; ".join(decision.reasons))
            halted = True
        except Conflict as exc:  # 그 사이 다른 전이가 일어났으면 다음 평가에서 다시 본다
            log.info("auto-halt skipped for rollout %s: %s", rid, exc)
    return {"rollout_id": rid, "state": ota.get_rollout(rid)["state"], "halt": decision.halt, "halted_now": halted,
            "reasons": decision.reasons, "window": asdict(window)}


def start_auto_halt(app: FastAPI, interval_s: float) -> threading.Event:
    stop = threading.Event()

    def loop():
        while not stop.wait(interval_s):
            ota: OtaStore = app.state.ota
            for r in ota.list_rollouts():
                if r["state"] != "active":
                    continue
                try:
                    result = evaluate_rollout(ota, r["id"], apply=True)
                    if result["halted_now"]:
                        log.warning("rollout %s auto-halted: %s", r["name"], result["reasons"])
                except Exception:  # 한 롤아웃 실패가 루프를 멈추지 않게 한다
                    log.exception("auto-halt evaluation failed for rollout %s", r["id"])

    threading.Thread(target=loop, name="auto-halt", daemon=True).start()
    return stop


# --------------------------------------------------------------------------- #
# 라우터
# --------------------------------------------------------------------------- #
def build_router() -> APIRouter:
    router = APIRouter()

    def ota(request: Request) -> OtaStore:
        return request.app.state.ota

    # ------------------------------------------------------------------ device
    @router.post("/device/v1/update-check", dependencies=[Depends(require_device)])
    def device_update_check(body: UpdateCheckIn, store: OtaStore = Depends(ota)):
        return update_check(store, body)

    @router.post("/device/v1/events", status_code=202, dependencies=[Depends(require_device)])
    def device_events(body: EventsIn, store: OtaStore = Depends(ota)):
        events = []
        for event in body.events:
            if event.type == "error" and event.error_code is None:
                raise HTTPException(422, "error events require error_code")
            data = event.model_dump()
            data["occurred_at"] = event.occurred_at.isoformat()
            events.append(data)
        accepted, duplicates = store.record_events(body.device_hash, events)
        return {"accepted": accepted, "duplicates": duplicates}

    # ------------------------------------------------------------------ fleet
    @router.get("/admin/v1/devices")
    def list_devices(q: str = Query(default="", max_length=256), device: str | None = None,
                     channel: Literal["testing", "beta", "stable"] | None = None,
                     tag: str | None = Query(default=None, max_length=32),
                     seen_within_hours: int | None = Query(default=None, ge=1, le=24 * 365),
                     limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
                     _: Principal = Depends(ANY), store: OtaStore = Depends(ota)):
        return store.list_devices(q=q, device=device, channel=channel, tag=tag,
                                  seen_within_hours=seen_within_hours, limit=limit, offset=offset)

    @router.get("/admin/v1/devices/summary")
    def fleet_summary(_: Principal = Depends(ANY), store: OtaStore = Depends(ota)):
        return store.fleet_summary()

    @router.get("/admin/v1/devices/{device_hash}")
    def get_device(device_hash: Annotated[str, Field(pattern=SHA256_HEX)],
                   _: Principal = Depends(ANY), store: OtaStore = Depends(ota)):
        return store.get_device(device_hash)

    @router.put("/admin/v1/devices/{device_hash}/tags")
    def set_tags(device_hash: Annotated[str, Field(pattern=SHA256_HEX)], body: DeviceTagsIn,
                 who: Principal = Depends(OPERATOR), store: OtaStore = Depends(ota)):
        return store.set_device_tags(device_hash, body.tags, who.actor)

    # ------------------------------------------------------------------ packages
    @router.post("/admin/v1/packages/inspect")
    def inspect_package(body: InspectIn, request: Request, _: Principal = Depends(PIPELINE)):
        fp, info = _inspect(request, body.url)
        result = asdict(info)
        result.pop("metadata")
        return {**result, "ready": info.ready, "apply_payload_headers": info.apply_payload_headers(),
                "range_requests": getattr(fp, "requests", None), "bytes_fetched": getattr(fp, "bytes_fetched", None)}

    @router.post("/admin/v1/packages", status_code=201)
    def register_package(body: PackageIn, request: Request, who: Principal = Depends(PIPELINE),
                         store: OtaStore = Depends(ota)):
        _, info = _inspect(request, body.url)
        return store.register_package(body.url, info, body.sha256, who.actor)

    @router.get("/admin/v1/packages")
    def list_packages(device: str | None = None, _: Principal = Depends(ANY), store: OtaStore = Depends(ota)):
        return store.list_packages(device)

    @router.get("/admin/v1/packages/{pid}")
    def get_package(pid: int, _: Principal = Depends(ANY), store: OtaStore = Depends(ota)):
        return store.get_package(pid)

    @router.post("/admin/v1/packages/{pid}/retire")
    def retire_package(pid: int, who: Principal = Depends(RELEASE_MANAGER), store: OtaStore = Depends(ota)):
        return store.retire_package(pid, who.actor)

    # ------------------------------------------------------------------ rollouts
    @router.post("/admin/v1/rollouts", status_code=201)
    def create_rollout(body: RolloutIn, who: Principal = Depends(RELEASE_MANAGER), store: OtaStore = Depends(ota)):
        data = body.model_dump()
        data["filters"] = {k: v for k, v in data["filters"].items() if v}
        return store.create_rollout(data, who.actor)

    @router.get("/admin/v1/rollouts")
    def list_rollouts(_: Principal = Depends(ANY), store: OtaStore = Depends(ota)):
        return store.list_rollouts()

    @router.get("/admin/v1/rollouts/{rid}")
    def get_rollout(rid: int, _: Principal = Depends(ANY), store: OtaStore = Depends(ota)):
        return {**store.get_rollout(rid), "assignments": store.assignment_counts(rid)}

    for action, dep in (("start", RELEASE_MANAGER), ("promote", RELEASE_MANAGER), ("complete", RELEASE_MANAGER),
                        ("pause", OPERATOR), ("resume", OPERATOR), ("halt", OPERATOR)):
        def endpoint(rid: int, body: ReasonIn | None = None, who: Principal = Depends(dep),
                     store: OtaStore = Depends(ota), _action: str = action):
            return store.transition(rid, _action, who.actor, reason=body.reason if body else None)

        router.add_api_route(f"/admin/v1/rollouts/{{rid}}/{action}", endpoint, methods=["POST"],
                             name=f"rollout_{action}")

    @router.get("/admin/v1/rollouts/{rid}/metrics")
    def rollout_metrics(rid: int, window_minutes: int | None = None, _: Principal = Depends(ANY),
                        store: OtaStore = Depends(ota)):
        store.get_rollout(rid)
        window = store.rollout_window(rid, window_minutes)
        return {"rollout_id": rid, "assignments": store.assignment_counts(rid), "window": asdict(window),
                "errors": [{"code": code, "name": ERROR_NAMES.get(code, f"ErrorCode{code}"), "devices": n}
                           for code, n in sorted(window.failed_by_code.items(), key=lambda kv: -kv[1])]}

    @router.get("/admin/v1/rollouts/{rid}/preview")
    def rollout_preview(rid: int, _: Principal = Depends(ANY), store: OtaStore = Depends(ota)):
        return preview_rollout(store, rid)

    @router.get("/admin/v1/rollouts/{rid}/promotion-status")
    def promotion_status(rid: int, _: Principal = Depends(ANY), store: OtaStore = Depends(ota)):
        return store.promotion_status(rid)

    @router.get("/admin/v1/rollouts/{rid}/timeseries")
    def rollout_timeseries(rid: int, hours: int = 48, _: Principal = Depends(ANY), store: OtaStore = Depends(ota)):
        if not 1 <= hours <= 24 * 14:
            raise HTTPException(422, "hours must be between 1 and 336")
        store.get_rollout(rid)
        return store.timeseries(rid, hours)

    @router.post("/admin/v1/rollouts/{rid}/evaluate-halt")
    def rollout_evaluate(rid: int, apply: bool = False, who: Principal = Depends(OPERATOR),
                         store: OtaStore = Depends(ota)):
        return evaluate_rollout(store, rid, apply, actor=who.actor)

    @router.get("/admin/v1/reports/delta-candidates")
    def delta_candidates(target_fingerprint: str, days: int = 14, _: Principal = Depends(RELEASE_MANAGER),
                         store: OtaStore = Depends(ota)):
        if not 1 <= days <= 90:
            raise HTTPException(422, "days must be between 1 and 90")
        return store.delta_candidates(target_fingerprint, days)

    return router
