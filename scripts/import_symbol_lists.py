"""ACK 브랜치(또는 GKI 릴리스 태그)의 KMI symbol list 전체를 받아 backend 에 등록한다.

    .venv/bin/python scripts/import_symbol_lists.py --branch android16-6.12 \
        --api http://127.0.0.1:8020 [--ref refs/tags/android16-6.12-2026-09_r1] [--api-key KEY]

GKI 커널은 브랜치의 모든 symbol list 합집합을 export 하므로 vendor 파일 하나가 아니라 전체를 등록한다.
경로: android16-6.12 이후 `gki/aarch64/symbols/<vendor>`, 이전 `android/abi_gki_aarch64*`
(`abi_gki_protected_exports_aarch64` = 보호된 GKI 모듈 export 포함, `.stg` ABI 표현은 제외).
"""
from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.error
import urllib.request
import uuid

GITILES = "https://android.googlesource.com/kernel/common/+/{ref}/"
LAYOUTS = ("gki/aarch64/symbols/", "android/")


def fetch(url: str, attempts: int = 6) -> bytes:
    """gitiles 는 연속 요청에 429 를 준다 — Retry-After(없으면 지수 백오프)만큼 기다린 뒤 재시도."""
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == attempts - 1:
                raise
            delay = int(exc.headers.get("Retry-After") or 2 ** (attempt + 1))
            time.sleep(min(delay, 60))
    raise AssertionError("unreachable")


def list_files(ref: str) -> tuple[str, list[str]]:
    for layout in LAYOUTS:
        try:
            raw = fetch(GITILES.format(ref=ref) + layout + "?format=JSON").decode()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        listing = json.loads(raw.split("\n", 1)[1])  # gitiles XSSI prefix ")]}'"
        names = [e["name"] for e in listing["entries"] if e["type"] == "blob" and ".stg" not in e["name"]]
        if layout == "android/":
            names = [n for n in names if n.startswith(("abi_gki_aarch64", "abi_gki_protected_exports_aarch64"))]
        if names:
            return layout, sorted(names)
    raise SystemExit(f"no symbol lists found under {', '.join(LAYOUTS)} at {ref}")


def upload(api: str, api_key: str | None, branch: str, source: str, files: dict[str, bytes]) -> dict:
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="source"\r\n\r\n{source}\r\n'.encode()]
    for name, data in files.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
                     f"Content-Type: text/plain\r\n\r\n".encode() + data + b"\r\n")
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{api.rstrip('/')}/admin/v1/kernel/symbol-lists/{branch}", data=body,
                                 headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"upload failed: HTTP {exc.code} {exc.read().decode(errors='replace')}") from exc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--branch", required=True, help="ACK 브랜치 (예: android16-6.12)")
    ap.add_argument("--ref", help="gitiles ref (기본 refs/heads/<branch>, 예: refs/tags/android16-6.12-2026-09_r1)")
    ap.add_argument("--api", default="http://127.0.0.1:8020")
    ap.add_argument("--api-key")
    args = ap.parse_args()

    ref = args.ref or f"refs/heads/{args.branch}"
    layout, names = list_files(ref)
    print(f"{ref}: {len(names)} files under {layout}")
    files = {n: base64.b64decode(fetch(GITILES.format(ref=ref) + layout + n + "?format=TEXT")) for n in names}
    result = upload(args.api, args.api_key, args.branch, GITILES.format(ref=ref) + layout, files)
    print(f"  {result['branch']}: {result['symbol_count']} symbols")


if __name__ == "__main__":
    main()
