"""실기기 OTA 검증 (P0 잔여): backend update-check → update_engine_client 스트리밍 설치 → 이벤트 보고.

    # 1) 확인만 (기기 상태로 update-check, 설치하지 않음)
    python3 scripts/device_ota_test.py --api http://HOST:8020 --channel testing
    # 2) 설치 (userdebug/eng 빌드에서 `adb root` 필요)
    python3 scripts/device_ota_test.py --api http://HOST:8020 --channel testing --apply
    # 3) 재부팅 후 체크인 → 서버가 boot_success / boot_fallback 판정
    python3 scripts/device_ota_test.py --api http://HOST:8020 --channel testing

update_engine_client 플래그(--update --follow --payload --offset --size --headers, 헤더는 줄바꿈 구분)는
system/update_engine/aosp/update_engine_client_android.cc 기준이다.
설치 명령 종료코드만으로는 세부 ErrorCode 를 알 수 없어 실패 시 kError(1) 로 보고하고 logcat 확인을 안내한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

PROPS = {
    "device": "ro.product.device",
    "fingerprint": "ro.build.fingerprint",
    "incremental": "ro.build.version.incremental",
    "build_timestamp": "ro.build.date.utc",
    "security_patch": "ro.build.version.security_patch",
    "sdk_level": "ro.build.version.sdk",
    "slot_suffix": "ro.boot.slot_suffix",
    "serial": "ro.serialno",
}


def adb(serial: str | None, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["adb", *(["-s", serial] if serial else []), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def read_props(serial: str | None) -> dict[str, str]:
    out = {}
    for key, prop in PROPS.items():
        out[key] = adb(serial, "shell", "getprop", prop).stdout.strip()
    return out


def read_boot_id(serial: str | None) -> str:
    """재부팅마다 바뀌는 커널 boot_id — 서버가 재부팅 전 체크인과 부팅 폴백을 구별하는 데 쓴다."""
    return adb(serial, "shell", "cat", "/proc/sys/kernel/random/boot_id").stdout.strip()


def build_check_request(props: dict[str, str], channel: str, salt: str) -> dict:
    missing = [k for k in ("device", "fingerprint", "build_timestamp", "security_patch") if not props.get(k)]
    if missing:
        raise ValueError(f"device properties missing: {', '.join(missing)}")
    return {
        "device": props["device"],
        "fingerprint": props["fingerprint"],
        "incremental": props.get("incremental") or None,
        "build_timestamp": int(props["build_timestamp"]),
        "security_patch": props["security_patch"],
        "sdk_level": int(props["sdk_level"]) if props.get("sdk_level", "").isdigit() else None,
        "slot_suffix": props.get("slot_suffix") or None,
        "boot_id": props.get("boot_id") or None,
        "channel": channel,
        # 기기 식별자는 원문을 보내지 않는다 (NF-07)
        "device_hash": hashlib.sha256(f"{salt}:{props.get('serial', '')}".encode()).hexdigest(),
    }


def install_command(update: dict) -> str:
    """adb shell 로 넘길 원격 명령 문자열 (원격 sh 가 다시 파싱하므로 인자별로 quote)."""
    pkg = update["package"]
    args = ["update_engine_client", "--update", "--follow", f"--payload={pkg['url']}",
            f"--offset={pkg['payload_offset']}", f"--size={pkg['payload_size']}",
            "--headers=" + "\n".join(pkg["headers"])]
    return " ".join(shlex.quote(a) for a in args)


def post(api: str, path: str, body: dict, key: str | None) -> dict:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(api.rstrip("/") + path, data=json.dumps(body).encode(), headers=headers,
                                 method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def event(assignment_id: int, attempt: int, kind: str, **extra) -> dict:
    return {"assignment_id": assignment_id, "attempt": attempt, "type": kind,
            "occurred_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **extra}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", required=True)
    ap.add_argument("--device-key", help="ANDROID_OS_DEVICE_KEYS 중 하나")
    ap.add_argument("--serial", help="adb -s")
    ap.add_argument("--channel", default="testing", choices=["testing", "beta", "stable"])
    ap.add_argument("--salt", default="android-os-device-test")
    ap.add_argument("--apply", action="store_true", help="update_engine_client 로 실제 설치")
    args = ap.parse_args()

    props = {**read_props(args.serial), "boot_id": read_boot_id(args.serial)}
    request = build_check_request(props, args.channel, args.salt)
    print(f"device={request['device']} fingerprint={request['fingerprint']} slot={request['slot_suffix']}")
    update = post(args.api, "/device/v1/update-check", request, args.device_key)
    print(json.dumps(update, indent=2, ensure_ascii=False))
    if not update.get("update_available") or not args.apply:
        return 0

    aid, attempt = update["assignment_id"], update["attempt"]
    command = install_command(update)
    print(f"\n$ adb shell {command}\n")
    post(args.api, "/device/v1/events", {"device_hash": request["device_hash"],
                                         "events": [event(aid, attempt, "download_started")]}, args.device_key)
    result = subprocess.run(["adb", *(["-s", args.serial] if args.serial else []), "shell", command])
    if result.returncode == 0:
        post(args.api, "/device/v1/events", {"device_hash": request["device_hash"],
                                             "events": [event(aid, attempt, "updated_need_reboot", boot_id=request["boot_id"])]}, args.device_key)
        print("설치 완료. `adb reboot` 후 이 스크립트를 --apply 없이 다시 실행해 부팅 결과를 체크인하세요.")
        return 0
    post(args.api, "/device/v1/events", {"device_hash": request["device_hash"],
                                         "events": [event(aid, attempt, "error", error_code=1)]}, args.device_key)
    print("설치 실패. 세부 ErrorCode: `adb logcat -s update_engine` 확인", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
