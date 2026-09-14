"""AOSP 릴리스 태그의 framework compatibility matrix 를 받아 backend 에 등록한다.

    .venv/bin/python scripts/import_matrices.py --release 17 --tag android-17.0.0_r1 \
        --api http://127.0.0.1:8020 [--levels 8,202604] [--api-key KEY]

main 브랜치 파일은 레벨 번호만 바뀐 복사본일 수 있으므로 반드시 릴리스 태그를 지정한다.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import urllib.request
import uuid

GITILES = "https://android.googlesource.com/platform/hardware/interfaces/+/refs/tags/{tag}/compatibility_matrices/"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def list_levels(tag: str) -> list[str]:
    raw = fetch(GITILES.format(tag=tag) + "?format=JSON").decode()
    listing = json.loads(raw.split("\n", 1)[1])  # gitiles XSSI prefix ")]}'"
    return sorted({m[1] for e in listing["entries"] if (m := re.fullmatch(r"compatibility_matrix\.(\d+)\.xml", e["name"]))},
                  key=int)


def upload(api: str, api_key: str | None, release: str, source: str, xml: bytes) -> dict:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("release", release), ("source", source)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="matrix.xml"\r\n'
                 f"Content-Type: application/xml\r\n\r\n".encode() + xml + b"\r\n")
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{api.rstrip('/')}/admin/v1/matrices", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release", required=True, help="KB 릴리스 이름 (예: 17)")
    ap.add_argument("--tag", required=True, help="AOSP 태그 (예: android-17.0.0_r1)")
    ap.add_argument("--api", default="http://127.0.0.1:8020")
    ap.add_argument("--api-key")
    ap.add_argument("--levels", help="쉼표 구분 레벨. 생략하면 태그의 전체 레벨")
    args = ap.parse_args()

    levels = args.levels.split(",") if args.levels else list_levels(args.tag)
    print(f"{args.tag}: levels {', '.join(levels)}")
    for level in levels:
        path = GITILES.format(tag=args.tag) + f"compatibility_matrix.{level}.xml"
        xml = base64.b64decode(fetch(path + "?format=TEXT"))
        result = upload(args.api, args.api_key, args.release, path, xml)
        print(f"  level {result['level']}: {result['hal_count']} HALs")


if __name__ == "__main__":
    main()
