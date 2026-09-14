"""android-os backend — P1 Readiness MVP (+ OTA 패키지 원격 검사).

    .venv/bin/uvicorn --factory backend.app:create_app --port 8020 --reload

API (docs/design/04-api-spec.md §2 의 부분집합):
  GET   /api/health
  GET   /admin/v1/kb/releases
  POST  /admin/v1/platforms                         플랫폼 프로파일 등록
  GET   /admin/v1/platforms · /admin/v1/platforms/{id}
  PUT   /admin/v1/platforms/{id}/manifest           device manifest + vintf fragments (multipart files)
  POST  /admin/v1/platforms/{id}/readiness-runs     {target_release, as_of?}
  GET   /admin/v1/platforms/{id}/readiness-runs
  GET   /admin/v1/readiness-runs/{id}
  PATCH /admin/v1/work-items/{id}
  POST  /admin/v1/matrices                          framework compatibility matrix 업로드 (release + file)
  GET   /admin/v1/matrices
  POST  /admin/v1/vintf/matrix-diff                 두 matrix XML 비교 (old, new)
  GET   /admin/v1/audit
  + OTA Delivery (P2~P4): backend/ota_api.py 참조

인증: ANDROID_OS_API_KEYS="key:actor:role,..." (Authorization: Bearer <key>).
기기 API: ANDROID_OS_DEVICE_KEYS="key1,key2". 패키지 오리진: ANDROID_OS_PACKAGE_HOSTS="host1,host2".
세 설정이 없으면 시작을 거부한다. ANDROID_OS_DEV_MODE=1 일 때만 인증 없이(actor=dev) 동작하고
패키지 호스트 제한을 끈다.
자동 halt: ANDROID_OS_AUTO_HALT_INTERVAL_S (기본 300, 0 이면 비활성).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from upgrade_core import __version__
from upgrade_core.readiness import PlatformProfile, evaluate, load_kb, release_key
from upgrade_core.vintf import VintfError, diff_matrices, parse_manifest, parse_matrix

from .auth import ANY, ENGINEER, Principal, parse_api_keys, parse_device_keys, require
from .ota_api import PackageOpener, build_router, https_range_opener, start_auto_halt
from .ota_store import OtaStore
from .store import Conflict, NotFound, Store

log = logging.getLogger("android_os")
MAX_XML_BYTES = 2 * 1024 * 1024


# --------------------------------------------------------------------------- #
# 요청 모델
# --------------------------------------------------------------------------- #
class PlatformIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    soc: str = Field(min_length=1, max_length=100)
    android_version: str = Field(examples=["16"])
    kernel_branch: str = Field(pattern=r"^android\d+-\d+\.\d+$", examples=["android16-6.12"])
    fcm_target_level: str | None = Field(default=None, pattern=r"^\d+$")
    uses_vndk: bool = False
    uses_ion: bool = False
    supports_16kb: bool = False
    sepolicy_memfd_ready: bool = False
    support_until: date | None = None


class RunIn(BaseModel):
    target_release: str = Field(examples=["17"])
    as_of: date | None = None


class WorkItemPatch(BaseModel):
    status: Literal["todo", "in_progress", "done", "waived"] | None = None
    owner: str | None = None
    waive_reason: str | None = None
    external_ref: str | None = None


# --------------------------------------------------------------------------- #
# 앱
# --------------------------------------------------------------------------- #
def _setting(value, env: str, default: str = "") -> str:
    return value if value is not None else os.environ.get(env, default)


def create_app(store: Store | None = None, api_keys: str | None = None, package_hosts: str | None = None,
               device_keys: str | None = None, package_opener: PackageOpener | None = None,
               auto_halt_interval_s: float | None = None, dev_mode: bool | None = None) -> FastAPI:
    dev = dev_mode if dev_mode is not None else os.environ.get("ANDROID_OS_DEV_MODE") == "1"
    parsed_api_keys = parse_api_keys(_setting(api_keys, "ANDROID_OS_API_KEYS"))
    parsed_device_keys = parse_device_keys(_setting(device_keys, "ANDROID_OS_DEVICE_KEYS"))
    hosts = {h.strip() for h in _setting(package_hosts, "ANDROID_OS_PACKAGE_HOSTS").split(",") if h.strip()}
    if not dev:
        missing = [name for name, value in (("ANDROID_OS_API_KEYS", parsed_api_keys),
                                            ("ANDROID_OS_DEVICE_KEYS", parsed_device_keys),
                                            ("ANDROID_OS_PACKAGE_HOSTS", hosts or package_opener)) if not value]
        if missing:
            raise RuntimeError(f"missing {', '.join(missing)} (set ANDROID_OS_DEV_MODE=1 for local development)")
    interval = auto_halt_interval_s if auto_halt_interval_s is not None else \
        float(os.environ.get("ANDROID_OS_AUTO_HALT_INTERVAL_S", "300"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = start_auto_halt(app, interval) if interval > 0 else None
        yield
        if stop:
            stop.set()

    app = FastAPI(title="android-os backend", version=__version__, lifespan=lifespan)
    app.state.store = store or Store(os.environ.get("ANDROID_OS_DB", "android_os.db"))
    app.state.ota = OtaStore(app.state.store)
    app.state.dev_mode = dev
    app.state.api_keys = parsed_api_keys
    app.state.device_keys = parsed_device_keys
    app.state.package_hosts = hosts
    app.state.package_opener = package_opener or https_range_opener(hosts, restrict=not dev)
    if dev:
        log.warning("ANDROID_OS_DEV_MODE=1: authentication and package host restrictions are relaxed")

    def db(request: Request) -> Store:
        return request.app.state.store

    @app.exception_handler(NotFound)
    def _not_found(_: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"error": {"code": "NOT_FOUND", "message": str(exc)}})

    @app.exception_handler(Conflict)
    def _conflict(_: Request, exc: Conflict):
        return JSONResponse(status_code=409, content={"error": {"code": "CONFLICT", "message": str(exc)}})

    @app.exception_handler(VintfError)
    def _vintf(_: Request, exc: VintfError):
        return JSONResponse(status_code=422, content={"error": {"code": "INVALID_VINTF", "message": str(exc)}})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "kb_version": load_kb()["kb_version"]}

    @app.get("/admin/v1/overview")
    def overview(request: Request, _: Principal = Depends(ANY), store: Store = Depends(db)):
        return {**store.readiness_overview(), **request.app.state.ota.overview(),
                "kb_version": load_kb()["kb_version"], "dev_mode": request.app.state.dev_mode}

    @app.get("/admin/v1/kb/releases")
    def kb_releases(_: Principal = Depends(ANY)):
        return load_kb()

    # ------------------------------------------------------------------ platforms
    @app.post("/admin/v1/platforms", status_code=201)
    def create_platform(body: PlatformIn, who: Principal = Depends(ENGINEER), store: Store = Depends(db)):
        _check_release(body.android_version)
        data = body.model_dump()
        data["support_until"] = body.support_until.isoformat() if body.support_until else None
        return store.create_platform(data, who.actor)

    @app.get("/admin/v1/platforms")
    def list_platforms(_: Principal = Depends(ANY), store: Store = Depends(db)):
        return store.list_platforms()

    @app.get("/admin/v1/platforms/{pid}")
    def get_platform(pid: int, _: Principal = Depends(ANY), store: Store = Depends(db)):
        return store.get_platform(pid)

    @app.put("/admin/v1/platforms/{pid}/manifest")
    async def upload_manifest(pid: int, files: list[UploadFile] = File(...), who: Principal = Depends(ENGINEER),
                              store: Store = Depends(db)):
        store.get_platform(pid)
        documents = [{"filename": f.filename, "xml": await _read_xml(f)} for f in files]
        manifest = parse_manifest(*(d["xml"] for d in documents))
        platform = store.save_manifest(pid, documents, manifest.target_level, len(manifest.hals), who.actor)
        by_format: dict[str, int] = {}
        for hal in manifest.hals:
            by_format[hal.format] = by_format.get(hal.format, 0) + 1
        return {"platform": platform, "hal_instances_by_format": by_format,
                "hals": sorted({h.fqname for h in manifest.hals})}

    # ------------------------------------------------------------------ readiness
    @app.post("/admin/v1/platforms/{pid}/readiness-runs", status_code=201)
    def create_run(pid: int, body: RunIn, who: Principal = Depends(ENGINEER), store: Store = Depends(db)):
        platform = store.get_platform(pid)
        _check_release(body.target_release)
        profile = PlatformProfile(
            name=platform["name"], android_version=platform["android_version"],
            kernel_branch=platform["kernel_branch"], fcm_target_level=platform["fcm_target_level"],
            uses_vndk=platform["uses_vndk"], uses_ion=platform["uses_ion"], supports_16kb=platform["supports_16kb"],
            sepolicy_memfd_ready=platform["sepolicy_memfd_ready"],
            support_until=date.fromisoformat(platform["support_until"]) if platform["support_until"] else None,
        )
        manifest, matrix, hal_check = None, None, "skipped: no manifest uploaded"
        documents = store.manifest_documents(pid)
        if documents:
            manifest = parse_manifest(*(d["xml"] for d in documents))
            level = platform["fcm_target_level"]
            xml = _matrix_for(store, body.target_release, level) if level else None
            if xml:
                matrix = parse_matrix(xml)
                hal_check = f"included: matrix level {level}"
            else:
                hal_check = f"skipped: no framework matrix level {level} uploaded for release {body.target_release}"
        try:
            summary = evaluate(profile, body.target_release, body.as_of or date.today(),
                               manifest=manifest, target_matrix=matrix)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {**store.save_run(pid, summary, who.actor), "hal_check": hal_check}

    @app.get("/admin/v1/platforms/{pid}/readiness-runs")
    def list_runs(pid: int, _: Principal = Depends(ANY), store: Store = Depends(db)):
        store.get_platform(pid)
        return store.list_runs(pid)

    @app.get("/admin/v1/readiness-runs/{run_id}")
    def get_run(run_id: int, _: Principal = Depends(ANY), store: Store = Depends(db)):
        return store.get_run(run_id)

    @app.patch("/admin/v1/work-items/{item_id}")
    def patch_work_item(item_id: int, body: WorkItemPatch, who: Principal = Depends(ENGINEER),
                        store: Store = Depends(db)):
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, "no changes")
        return store.update_work_item(item_id, changes, who.actor)

    # ------------------------------------------------------------------ vintf
    @app.post("/admin/v1/matrices", status_code=201)
    async def upload_matrix(release: str = Form(...), source: str | None = Form(default=None),
                            file: UploadFile = File(...), who: Principal = Depends(ENGINEER),
                            store: Store = Depends(db)):
        _check_release(release)
        xml = await _read_xml(file)
        matrix = parse_matrix(xml)
        saved = store.save_matrix(release, matrix.level, xml, source, who.actor)
        return {**saved, "hal_count": len(matrix.hals)}

    @app.get("/admin/v1/matrices")
    def list_matrices(_: Principal = Depends(ANY), store: Store = Depends(db)):
        return store.list_matrices()

    @app.post("/admin/v1/vintf/matrix-diff")
    async def matrix_diff(old: UploadFile = File(...), new: UploadFile = File(...), _: Principal = Depends(ANY)):
        return asdict(diff_matrices(parse_matrix(await _read_xml(old)), parse_matrix(await _read_xml(new))))

    # ------------------------------------------------------------------ packages
    @app.get("/admin/v1/audit")
    def audit(entity: str | None = None, limit: int = 100, _: Principal = Depends(require("operator", "engineer")),
              store: Store = Depends(db)):
        return store.audit(entity, min(max(limit, 1), 1000))

    app.include_router(build_router())
    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """web/dist 가 있으면 / 에서 SPA 를 서빙한다 (API 경로가 먼저 매칭된다)."""
    dist = Path(os.environ.get("ANDROID_OS_WEB_DIST", Path(__file__).resolve().parent.parent / "web" / "dist"))
    index = dist / "index.html"
    if not index.is_file():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", ImmutableStaticFiles(directory=dist / "assets"), name="assets")
    no_cache = {"Cache-Control": "no-cache"}  # index.html 은 매번 재검증해야 새 해시 에셋을 받는다

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("admin/", "device/", "api/")):
            raise HTTPException(404, "not found")
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate, headers=no_cache)
        return FileResponse(index, headers=no_cache)


class ImmutableStaticFiles(StaticFiles):
    """Vite 빌드 에셋은 파일명에 콘텐츠 해시가 있어 영구 캐시해도 안전하다."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _check_release(release: str) -> None:
    try:
        release_key(release)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


async def _read_xml(upload: UploadFile) -> str:
    data = await upload.read(MAX_XML_BYTES + 1)
    if len(data) > MAX_XML_BYTES:
        raise HTTPException(413, f"{upload.filename}: XML larger than {MAX_XML_BYTES} bytes")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, f"{upload.filename}: not UTF-8") from exc


def _matrix_for(store: Store, release: str, level: str) -> str | None:
    """정확한 릴리스(17-QPR1) 매트릭스가 없으면 같은 메이저(17) 매트릭스를 사용한다."""
    return store.get_matrix_xml(release, level) or store.get_matrix_xml(str(release_key(release)[0]), level)

