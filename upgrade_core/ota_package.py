"""A/B OTA zip 파싱·검증 (요구사항 OT-01, OT-02, OT-13).

zip 을 풀지 않고 중앙 디렉터리와 로컬 헤더만 읽어 update_engine 스트리밍에 필요한
엔트리 offset/size 를 계산한다. metadata 는 레거시 텍스트(`META-INF/com/android/metadata`)를
사용한다 — metadata.pb 와 같은 정보이며 protobuf 의존이 필요 없다.
"""
from __future__ import annotations

import base64
import hashlib
import io
import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import BinaryIO

from .ota_metadata_pb import ProtoError, cross_check, parse_ota_metadata

METADATA_ENTRY = "META-INF/com/android/metadata"
METADATA_PB_ENTRY = METADATA_ENTRY + ".pb"
PAYLOAD = "payload.bin"
PAYLOAD_PROPERTIES = "payload_properties.txt"
PAYLOAD_MAGIC = b"CrAU"
# property-files 문자열의 이름 → zip 엔트리 경로 (ota_utils.py PropertyFiles)
PROPERTY_FILE_ALIASES = {"metadata": METADATA_ENTRY, "metadata.pb": METADATA_ENTRY + ".pb"}
REQUIRED_PAYLOAD_KEYS = ("FILE_HASH", "FILE_SIZE", "METADATA_HASH", "METADATA_SIZE")
# ota_utils.py 의 StreamingPropertyFiles: 필수 2개 + 존재하면 포함하는 선택 엔트리
STREAMING_OPTIONAL = ("apex_info.pb", "care_map.pb", "care_map.txt", "compatibility.zip")
LOCAL_HEADER = struct.Struct("<4sHHHHHIIIHH")
LOCAL_HEADER_MAGIC = b"PK\x03\x04"
# 악의적/손상 zip 에 대한 메모리 상한
MAX_CENTRAL_DIRECTORY = 4 * 1024 * 1024
MAX_TEXT_ENTRY = 1024 * 1024
MAX_METADATA_SIZE = 64 * 1024 * 1024
EOCD = struct.Struct("<4s4H2LH")            # end of central directory
ZIP64_LOCATOR = struct.Struct("<4sLQL")
ZIP64_EOCD = struct.Struct("<4sQ2H2L4Q")
MALFORMED_ZIP_ERRORS = (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, EOFError,
                        UnicodeDecodeError, struct.error)


class OtaPackageError(ValueError):
    """패키지를 해석할 수 없음(구조 오류). 검증 실패는 reject_reasons 로 표현한다."""


@dataclass(frozen=True)
class ZipEntry:
    name: str
    offset: int  # 엔트리 데이터 시작 위치(로컬 헤더 뒤)
    size: int    # 저장 크기
    stored: bool


@dataclass
class OtaPackageInfo:
    ota_type: str
    package_type: str  # full | incremental
    pre_device: list[str]
    pre_builds: list[str]
    post_build: str
    post_build_incremental: str
    post_timestamp: int
    post_spl: str
    post_sdk_level: int | None
    wipe: bool
    downgrade: bool
    spl_downgrade: bool
    payload_offset: int
    payload_size: int
    payload_properties: dict[str, str]
    streaming_property_files: str
    payload_metadata: ZipEntry | None
    file_size: int
    sha256: str
    metadata: dict[str, str] = field(repr=False)
    reject_reasons: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.reject_reasons

    def apply_payload_headers(self) -> list[str]:
        """UpdateEngine.applyPayload() headerKeyValuePairs 의 페이로드 부분."""
        return [f"{k}={self.payload_properties[k]}" for k in REQUIRED_PAYLOAD_KEYS]


def parse_key_values(text: str) -> dict[str, str]:
    """`key=value` 줄 형식(metadata, payload_properties.txt). 빈 줄은 무시, 첫 '=' 기준 분리."""
    out: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        key, sep, value = line.partition("=")
        if not sep or not key:
            raise OtaPackageError(f"line {lineno}: expected key=value, got {raw!r}")
        out[key.strip()] = value.strip()
    return out


def parse_property_files(value: str) -> dict[str, tuple[int, int]]:
    """`name:offset:size,...` 문자열. ota-property-files 는 뒤에 공백 패딩이 붙을 수 있다."""
    out: dict[str, tuple[int, int]] = {}
    for item in value.strip().split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.rsplit(":", 2)
        if len(parts) != 3:
            raise OtaPackageError(f"bad property-files item {item!r}")
        name, offset, size = parts
        try:
            out[name] = (int(offset), int(size))
        except ValueError as exc:
            raise OtaPackageError(f"bad property-files item {item!r}") from exc
    return out


def central_directory_size(fp: BinaryIO) -> int:
    """zipfile 이 중앙 디렉터리를 통째로 메모리에 읽기 전에 크기를 확인한다 (zip64 포함)."""
    total = fp.seek(0, io.SEEK_END)
    tail_len = min(total, EOCD.size + 0xFFFF)
    fp.seek(total - tail_len)
    tail = fp.read(tail_len)
    at = tail.rfind(b"PK\x05\x06")
    if at < 0 or at + EOCD.size > len(tail):
        raise OtaPackageError("not a zip file: end of central directory not found")
    cd_size = EOCD.unpack(tail[at:at + EOCD.size])[5]
    if cd_size == 0xFFFFFFFF and at >= ZIP64_LOCATOR.size:
        locator = ZIP64_LOCATOR.unpack(tail[at - ZIP64_LOCATOR.size:at])
        if locator[0] == b"PK\x06\x07":
            fp.seek(locator[2])
            record = fp.read(ZIP64_EOCD.size)
            if len(record) == ZIP64_EOCD.size and record[:4] == b"PK\x06\x06":
                cd_size = ZIP64_EOCD.unpack(record)[8]
    return cd_size


def zip_entries(fp: BinaryIO) -> dict[str, ZipEntry]:
    """중앙 디렉터리 + 로컬 헤더에서 각 엔트리의 데이터 offset 을 계산한다."""
    cd_size = central_directory_size(fp)
    if cd_size > MAX_CENTRAL_DIRECTORY:
        raise OtaPackageError(f"central directory too large ({cd_size} bytes)")
    try:
        zf = zipfile.ZipFile(fp)
    except zipfile.BadZipFile as exc:
        raise OtaPackageError(f"not a zip file: {exc}") from exc
    entries: dict[str, ZipEntry] = {}
    for info in zf.infolist():
        fp.seek(info.header_offset)
        header = fp.read(LOCAL_HEADER.size)
        if len(header) != LOCAL_HEADER.size:
            raise OtaPackageError(f"truncated local header for {info.filename}")
        fields = LOCAL_HEADER.unpack(header)
        if fields[0] != LOCAL_HEADER_MAGIC:
            raise OtaPackageError(f"bad local header magic for {info.filename}")
        name_len, extra_len = fields[9], fields[10]
        offset = info.header_offset + LOCAL_HEADER.size + name_len + extra_len
        entries[info.filename] = ZipEntry(info.filename, offset, info.compress_size,
                                          info.compress_type == zipfile.ZIP_STORED)
    return entries


def _read_entry(fp: BinaryIO, name: str) -> str:
    data = _read_entry_bytes(fp, name)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OtaPackageError(f"{name} is not UTF-8") from exc


def _read_entry_bytes(fp: BinaryIO, name: str) -> bytes:
    """작은 엔트리만 읽는다. 헤더의 크기를 믿지 않고 상한+1 까지만 푼다(zip bomb 방지)."""
    with zipfile.ZipFile(fp) as zf:
        info = zf.getinfo(name)
        if info.file_size > MAX_TEXT_ENTRY or info.compress_size > MAX_TEXT_ENTRY:
            raise OtaPackageError(f"{name} too large ({info.file_size} bytes)")
        with zf.open(info) as entry:
            data = entry.read(MAX_TEXT_ENTRY + 1)
    if len(data) > MAX_TEXT_ENTRY:
        raise OtaPackageError(f"{name} too large")
    return data


def _sha256(fp: BinaryIO) -> tuple[str, int]:
    fp.seek(0)
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: fp.read(1 << 20), b""):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _check_payload_head(fp: BinaryIO, payload: ZipEntry, props: dict[str, str]) -> list[str]:
    """payload.bin 매직과 METADATA_HASH(= payload 앞 METADATA_SIZE 바이트의 sha256, base64) 대조.

    update_engine 이 설치 시작 직후 검증하는 값이므로 등록 시점에 잡으면 기기 오류(26 등)를 막는다.
    원격 파일이어도 메타데이터 크기(수백 KB)만 읽는다.
    """
    fp.seek(payload.offset)
    if fp.read(4) != PAYLOAD_MAGIC:
        return ["payload.bin does not start with CrAU magic"]
    size = props.get("METADATA_SIZE", "")
    if not size.isdigit() or "METADATA_HASH" not in props:
        return []
    if int(size) > payload.size:
        return [f"METADATA_SIZE={size} exceeds payload.bin size {payload.size}"]
    if int(size) > MAX_METADATA_SIZE:
        return [f"METADATA_SIZE={size} exceeds limit {MAX_METADATA_SIZE}"]
    fp.seek(payload.offset)
    digest = hashlib.sha256()
    remaining = int(size)
    while remaining:
        chunk = fp.read(min(remaining, 1 << 20))
        if not chunk:
            return ["payload.bin truncated inside metadata"]
        digest.update(chunk)
        remaining -= len(chunk)
    actual = base64.b64encode(digest.digest()).decode()
    if actual != props["METADATA_HASH"]:
        return [f"METADATA_HASH mismatch (payload head hashes to {actual})"]
    return []


def _split_multi(value: str | None) -> list[str]:
    return [v for v in (value or "").split("|") if v]


def _flag(meta: dict[str, str], key: str) -> bool:
    return meta.get(key, "").lower() in ("yes", "true", "1")


def inspect_ota_package(fp: BinaryIO, compute_sha256: bool = True) -> OtaPackageInfo:
    """OTA zip 을 해석하고 배포 가능 여부를 검증한다. 구조적으로 해석 불가하면 OtaPackageError.

    compute_sha256=False 면 전체 파일을 읽지 않는다(원격 Range 검사용). 이때 sha256 은 빈 문자열이다.
    I/O 오류(OSError)는 그대로 전파하고, 손상된 zip 에서 나는 예외는 OtaPackageError 로 바꾼다.
    """
    try:
        return _inspect(fp, compute_sha256)
    except MALFORMED_ZIP_ERRORS as exc:
        raise OtaPackageError(f"malformed zip: {type(exc).__name__}: {exc}") from exc


def _inspect(fp: BinaryIO, compute_sha256: bool) -> OtaPackageInfo:
    entries = zip_entries(fp)
    for required in (METADATA_ENTRY, PAYLOAD, PAYLOAD_PROPERTIES):
        if required not in entries:
            raise OtaPackageError(f"missing zip entry {required}")

    meta = parse_key_values(_read_entry(fp, METADATA_ENTRY))
    props = parse_key_values(_read_entry(fp, PAYLOAD_PROPERTIES))
    reasons: list[str] = []
    if METADATA_PB_ENTRY in entries:
        try:
            reasons.extend(cross_check(meta, parse_ota_metadata(_read_entry_bytes(fp, METADATA_PB_ENTRY))))
        except ProtoError as exc:
            reasons.append(f"metadata.pb unreadable: {exc}")

    ota_type = meta.get("ota-type", "")
    if ota_type != "AB":
        reasons.append(f"ota-type={ota_type or '(missing)'}; only AB packages are supported")
    missing = [k for k in REQUIRED_PAYLOAD_KEYS if k not in props]
    if missing:
        reasons.append(f"payload_properties.txt missing {', '.join(missing)}")

    payload = entries[PAYLOAD]
    streaming_names = [PAYLOAD, PAYLOAD_PROPERTIES] + [n for n in STREAMING_OPTIONAL if n in entries]
    for name in streaming_names:
        if not entries[name].stored:
            reasons.append(f"{name} is compressed; streaming requires ZIP_STORED")
    if "FILE_SIZE" in props and props["FILE_SIZE"] != str(payload.size):
        reasons.append(f"FILE_SIZE={props['FILE_SIZE']} != payload.bin size {payload.size}")
    streaming = ",".join(f"{n}:{entries[n].offset}:{entries[n].size}" for n in streaming_names)

    declared = meta.get("ota-streaming-property-files")
    if declared:
        for name, location in parse_property_files(declared).items():
            entry = entries.get(PROPERTY_FILE_ALIASES.get(name, name))
            actual = (entry.offset, entry.size) if entry else None
            if location != actual:
                reasons.append(f"metadata {name} location {location} != actual {actual}")
    reasons.extend(_check_payload_head(fp, payload, props))

    pre_device = _split_multi(meta.get("pre-device"))
    pre_builds = _split_multi(meta.get("pre-build"))
    post_build = meta.get("post-build", "")
    if not pre_device:
        reasons.append("pre-device missing")
    if not post_build:
        reasons.append("post-build missing")
    try:
        post_timestamp = int(meta.get("post-timestamp", ""))
    except ValueError:
        post_timestamp = 0
        reasons.append("post-timestamp missing or not an integer")
    post_spl = meta.get("post-security-patch-level", "")
    if not post_spl:
        reasons.append("post-security-patch-level missing")
    sdk = meta.get("post-sdk-level", "")

    downgrade = _flag(meta, "ota-downgrade")
    if downgrade:
        reasons.append("ota-downgrade=yes; downgrade packages need explicit approval (OT-13)")

    if compute_sha256:
        digest, file_size = _sha256(fp)
    else:
        digest, file_size = "", fp.seek(0, io.SEEK_END)
    return OtaPackageInfo(
        ota_type=ota_type,
        package_type="incremental" if pre_builds else "full",
        pre_device=pre_device,
        pre_builds=pre_builds,
        post_build=post_build,
        post_build_incremental=meta.get("post-build-incremental", ""),
        post_timestamp=post_timestamp,
        post_spl=post_spl,
        post_sdk_level=int(sdk) if sdk.isdigit() else None,
        wipe=_flag(meta, "ota-wipe"),
        downgrade=downgrade,
        spl_downgrade=_flag(meta, "spl-downgrade"),
        payload_offset=payload.offset,
        payload_size=payload.size,
        payload_properties=props,
        streaming_property_files=streaming,
        payload_metadata=entries.get("payload_metadata.bin"),
        file_size=file_size,
        sha256=digest,
        metadata=meta,
        reject_reasons=reasons,
    )
