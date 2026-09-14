"""META-INF/com/android/metadata.pb (OtaMetadata protobuf) 해독 — protobuf 의존 없이 wire format 만 읽는다.

스키마: build/make/tools/releasetools/ota_metadata.proto
  OtaMetadata { OtaType type=1; bool wipe=2; bool downgrade=3; map<string,string> property_files=4;
                DeviceState precondition=5; DeviceState postcondition=6; bool retrofit_dynamic_partitions=7;
                int64 required_cache=8; bool spl_downgrade=9; }
  DeviceState { repeated string device=1; repeated string build=2; string build_incremental=3; int64 timestamp=4;
                string sdk_level=5; string security_patch_level=6; repeated PartitionState partition_state=7; }

레거시 텍스트 metadata 와 같은 정보이므로 등록 시 두 파일을 교차 검증한다(ADR D3 리스크 대응).
"""
from __future__ import annotations

from dataclasses import dataclass, field

OTA_TYPES = {0: "UNKNOWN", 1: "AB", 2: "BLOCK", 3: "BRICK"}
MAX_DEPTH = 4


class ProtoError(ValueError):
    pass


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(buf):
            raise ProtoError("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ProtoError("varint too long")


def fields(buf: bytes) -> list[tuple[int, int, int | bytes]]:
    """(field_number, wire_type, value) 목록. varint(0)·length-delimited(2)·fixed64(1)·fixed32(5) 지원."""
    out = []
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 2:
            length, pos = _varint(buf, pos)
            if pos + length > len(buf):
                raise ProtoError(f"field {number}: length {length} beyond buffer")
            value, pos = buf[pos:pos + length], pos + length
        elif wire == 1:
            value, pos = int.from_bytes(buf[pos:pos + 8], "little"), pos + 8
        elif wire == 5:
            value, pos = int.from_bytes(buf[pos:pos + 4], "little"), pos + 4
        else:
            raise ProtoError(f"unsupported wire type {wire} for field {number}")
        if pos > len(buf):
            raise ProtoError("truncated fixed field")
        out.append((number, wire, value))
    return out


def _text(value) -> str:
    if not isinstance(value, bytes):
        raise ProtoError("expected length-delimited string")
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtoError("invalid UTF-8 string") from exc


@dataclass
class DeviceState:
    device: list[str] = field(default_factory=list)
    build: list[str] = field(default_factory=list)
    build_incremental: str = ""
    timestamp: int = 0
    sdk_level: str = ""
    security_patch_level: str = ""


@dataclass
class OtaMetadataPb:
    type: str = "UNKNOWN"
    wipe: bool = False
    downgrade: bool = False
    property_files: dict[str, str] = field(default_factory=dict)
    precondition: DeviceState = field(default_factory=DeviceState)
    postcondition: DeviceState = field(default_factory=DeviceState)
    required_cache: int = 0
    spl_downgrade: bool = False


def _device_state(buf: bytes) -> DeviceState:
    state = DeviceState()
    for number, _, value in fields(buf):
        if number == 1:
            state.device.append(_text(value))
        elif number == 2:
            state.build.append(_text(value))
        elif number == 3:
            state.build_incremental = _text(value)
        elif number == 4:
            state.timestamp = int(value)
        elif number == 5:
            state.sdk_level = _text(value)
        elif number == 6:
            state.security_patch_level = _text(value)
    return state


def parse_ota_metadata(buf: bytes) -> OtaMetadataPb:
    meta = OtaMetadataPb()
    for number, wire, value in fields(buf):
        if number == 1 and wire == 0:
            meta.type = OTA_TYPES.get(int(value), f"UNKNOWN({value})")
        elif number == 2 and wire == 0:
            meta.wipe = bool(value)
        elif number == 3 and wire == 0:
            meta.downgrade = bool(value)
        elif number == 4 and wire == 2:
            entry = {n: v for n, _, v in fields(value)}
            meta.property_files[_text(entry.get(1, b""))] = _text(entry.get(2, b""))
        elif number == 5 and wire == 2:
            meta.precondition = _device_state(value)
        elif number == 6 and wire == 2:
            meta.postcondition = _device_state(value)
        elif number == 8 and wire == 0:
            meta.required_cache = int(value)
        elif number == 9 and wire == 0:
            meta.spl_downgrade = bool(value)
    return meta


def _yes(text: dict[str, str], key: str) -> bool:
    return text.get(key, "").lower() in ("yes", "true", "1")


def cross_check(text: dict[str, str], pb: OtaMetadataPb) -> list[str]:
    """텍스트 metadata 와 metadata.pb 가 같은 사실을 말하는지 확인한다. 불일치 사유 목록."""
    pairs = [
        ("ota-type", text.get("ota-type", ""), pb.type),
        ("pre-device", text.get("pre-device", ""), "|".join(pb.precondition.device)),
        ("pre-build", text.get("pre-build", ""), "|".join(pb.precondition.build)),
        ("post-build", text.get("post-build", ""), "|".join(pb.postcondition.build)),
        ("post-build-incremental", text.get("post-build-incremental", ""), pb.postcondition.build_incremental),
        ("post-timestamp", text.get("post-timestamp", ""), str(pb.postcondition.timestamp or "")),
        ("post-security-patch-level", text.get("post-security-patch-level", ""),
         pb.postcondition.security_patch_level),
        ("post-sdk-level", text.get("post-sdk-level", ""), pb.postcondition.sdk_level),
        ("ota-wipe", _yes(text, "ota-wipe"), pb.wipe),
        ("ota-downgrade", _yes(text, "ota-downgrade"), pb.downgrade),
        ("spl-downgrade", _yes(text, "spl-downgrade"), pb.spl_downgrade),
    ]
    reasons = [f"metadata.pb {key}={pb_value!r} != metadata {text_value!r}"
               for key, text_value, pb_value in pairs if text_value != pb_value]
    for key in ("ota-streaming-property-files", "ota-property-files"):
        if key in text and key in pb.property_files and text[key].strip() != pb.property_files[key].strip():
            reasons.append(f"metadata.pb {key} differs from metadata")
    return reasons
