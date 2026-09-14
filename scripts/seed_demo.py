"""데모 데이터 적재 — 개발 모드 서버(ANDROID_OS_DEV_MODE=1)에서 콘솔 화면을 확인하기 위한 것.

    .venv/bin/python scripts/seed_demo.py --api http://127.0.0.1:8020 [--devices 400]

실데이터: AOSP android-17.0.0_r1 compatibility matrix(tests/fixtures), 공개 OTA 패키지
  (Google Pixel full OTA, GrapheneOS incremental OTA — HTTP Range 로 메타데이터만 읽음).
시뮬레이션: 플랫폼 프로파일과 기기 체크인·설치 이벤트(device_hash 는 'demo-device-N' 해시).
운영 DB 에는 사용하지 말 것.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "vintf"

TOKAY_TARGET = "google/tokay/tokay:17/CP2A.260805.005/2026091000:user/release-keys"
TOKAY_SOURCES = {
    "google/tokay/tokay:17/CP2A.260805.005/2026090700:user/release-keys": "2026090700",
    "google/tokay/tokay:17/CP2A.260805.005/2026090500:user/release-keys": "2026090500",
}
TOKAY_OLD = "google/tokay/tokay:17/CP2A.260705.004/2026072100:user/release-keys"
PACKAGES = [
    "https://releases.grapheneos.org/tokay-ota_update-2026091000.zip",
    "https://releases.grapheneos.org/tokay-incremental-2026090700-2026091000.zip",
    "https://releases.grapheneos.org/tokay-incremental-2026090500-2026091000.zip",
    "https://dl.google.com/dl/android/aosp/lynx-ota-cp2a.260705.006-f4d6d546.zip",
]

PLATFORMS = [
    {"name": "tokay-bsp", "soc": "tensor-g4", "android_version": "16", "kernel_branch": "android16-6.12",
     "supports_16kb": True, "sepolicy_memfd_ready": True, "support_until": "2031-08-31"},
    {"name": "legacy-5.10-bsp", "soc": "soc-2022", "android_version": "15", "kernel_branch": "android13-5.10",
     "uses_ion": True, "uses_vndk": True, "support_until": "2029-12-31"},
    {"name": "mid-6.6-bsp", "soc": "soc-2024", "android_version": "16", "kernel_branch": "android15-6.6",
     "fcm_target_level": "6", "support_until": "2030-06-30"},
]


def call(api: str, method: str, path: str, body=None, form: list[tuple[str, str, bytes]] | None = None):
    headers = {}
    data = None
    if form is not None:
        boundary = uuid.uuid4().hex
        parts = []
        for name, filename, content in form:
            disp = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
            parts.append(f"--{boundary}\r\nContent-Disposition: {disp}\r\n\r\n".encode() + content + b"\r\n")
        data = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(api.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            text = resp.read()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail[:300]}") from None


def dhash(i: int) -> str:
    return hashlib.sha256(f"demo-device-{i}".encode()).hexdigest()


def ts(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


def seed(api: str, devices: int) -> None:
    health = call(api, "GET", "/api/health")
    print(f"server {health['version']} · KB {health['kb_version']}")

    print("matrices: android-17.0.0_r1 level 8, 202604")
    for release, name in (("17", "a17.8.xml"), ("17", "a17.202604.xml")):
        call(api, "POST", "/admin/v1/matrices", form=[
            ("release", "", release.encode()),
            ("source", "", f"https://android.googlesource.com/platform/hardware/interfaces/+/refs/tags/android-17.0.0_r1/compatibility_matrices/compatibility_matrix.{name.split('.')[1]}.xml".encode()),
            ("file", name, (FIX / name).read_bytes())])

    existing = {p["name"]: p for p in call(api, "GET", "/admin/v1/platforms")}
    for spec in PLATFORMS:
        p = existing.get(spec["name"]) or call(api, "POST", "/admin/v1/platforms", spec)
        if spec["name"] == "tokay-bsp":
            manifest = b'<manifest version="1.0" type="device" target-level="8"><hal format="hidl"><name>android.hardware.graphics.mapper</name><transport>passthrough</transport><fqname>@4.0::IMapper/default</fqname></hal></manifest>'
            call(api, "PUT", f"/admin/v1/platforms/{p['id']}/manifest", form=[
                ("files", "manifest.xml", manifest), ("files", "health.xml", (FIX / "frag.health.xml").read_bytes()),
                ("files", "vibrator.xml", (FIX / "frag.vib.xml").read_bytes())])
        run = call(api, "POST", f"/admin/v1/platforms/{p['id']}/readiness-runs", {"target_release": "17"})
        print(f"platform {spec['name']}: ready={run['ready']} counts={run['counts']}")

    registered = {p["url"] for p in call(api, "GET", "/admin/v1/packages")}
    for url in PACKAGES:
        if url in registered:
            continue
        pkg = call(api, "POST", "/admin/v1/packages", {"url": url})
        print(f"package {url.rsplit('/', 1)[1]}: {pkg['status']} ({pkg['type']})")

    rollouts = {r["name"]: r for r in call(api, "GET", "/admin/v1/rollouts")}
    if "tokay-2026091000" in rollouts:
        print("rollout already seeded")
        return
    r = call(api, "POST", "/admin/v1/rollouts", {
        "name": "tokay-2026091000", "target_fingerprint": TOKAY_TARGET, "channel": "stable",
        "stages": [{"percent": 5, "min_soak_hours": 0}, {"percent": 25, "min_soak_hours": 24}, {"percent": 100, "min_soak_hours": 48}],
        "halt_rules": {"min_sample": 50, "max_error_rate": 0.08, "max_boot_fallback_rate": 0.02},
    })
    call(api, "POST", f"/admin/v1/rollouts/{r['id']}/start")
    call(api, "POST", f"/admin/v1/rollouts/{r['id']}/promote")  # 5% 단계 soak 0h → 25%

    rng = random.Random(7)
    sources = list(TOKAY_SOURCES) + [TOKAY_OLD]
    weights = [0.55, 0.3, 0.15]
    offered = 0
    for i in range(devices):
        fp = rng.choices(sources, weights)[0]
        boot = str(uuid.UUID(int=rng.getrandbits(128)))
        body = {"device": "tokay", "fingerprint": fp, "build_timestamp": 1787000000, "security_patch": "2026-08-05",
                "channel": "stable", "device_hash": dhash(i), "boot_id": boot}
        res = call(api, "POST", "/device/v1/update-check", body)
        if not res.get("update_available"):
            continue
        offered += 1
        aid, attempt = res["assignment_id"], res["attempt"]
        roll = rng.random()
        start = rng.uniform(60, 60 * 60)
        events = [{"assignment_id": aid, "attempt": attempt, "type": "download_started", "occurred_at": ts(start)}]
        if roll < 0.06:  # 설치 실패 (공간 부족·전송 오류)
            code = rng.choice([60, 60, 9, (1 << 30) | 9])
            events.append({"assignment_id": aid, "attempt": attempt, "type": "error", "error_code": code, "occurred_at": ts(start - 5)})
        elif roll < 0.2:  # 다운로드 중
            pass
        else:
            events.append({"assignment_id": aid, "attempt": attempt, "type": "updated_need_reboot", "boot_id": boot,
                           "occurred_at": ts(start - 20)})
        call(api, "POST", "/device/v1/events", {"device_hash": dhash(i), "events": events})
        if roll >= 0.25:  # 재부팅 후 체크인
            fallback = rng.random() < 0.01
            after = {**body, "boot_id": str(uuid.UUID(int=rng.getrandbits(128)))}
            if not fallback:
                after.update(fingerprint=TOKAY_TARGET, build_timestamp=1789042775, security_patch="2026-09-01")
            call(api, "POST", "/device/v1/update-check", after)
    print(f"simulated {devices} tokay devices, {offered} offered")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://127.0.0.1:8020")
    ap.add_argument("--devices", type=int, default=400)
    args = ap.parse_args()
    try:
        seed(args.api, args.devices)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
