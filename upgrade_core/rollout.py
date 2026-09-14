"""롤아웃 버킷팅·부팅 판정·에러코드 분해·자동 halt 평가 (OT-06, OT-08, OT-09, OT-10)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

BUCKETS = 10_000

# system/update_engine/common/error_code.h
ERROR_FLAGS = {1 << 31: "DevMode", 1 << 30: "Resumed", 1 << 29: "TestImage", 1 << 28: "TestOmahaUrl"}
SPECIAL_FLAGS_MASK = sum(ERROR_FLAGS)
OMAHA_HTTP_RESPONSE_BASE = 2000
ERROR_NAMES = {
    0: "Success", 1: "Error", 4: "FilesystemCopierError", 5: "PostinstallRunnerError",
    6: "PayloadMismatchedType", 7: "InstallDeviceOpenError", 8: "KernelDeviceOpenError",
    9: "DownloadTransferError", 10: "PayloadHashMismatchError", 11: "PayloadSizeMismatchError",
    12: "DownloadPayloadVerificationError", 21: "DownloadInvalidMetadataMagicString",
    24: "DownloadMetadataSignatureError", 25: "DownloadMetadataSignatureVerificationError",
    26: "DownloadMetadataSignatureMismatch", 44: "UnsupportedMajorPayloadVersion",
    45: "UnsupportedMinorPayloadVersion", 47: "FilesystemVerifierError", 48: "UserCanceled",
    51: "PayloadTimestampError", 52: "UpdatedButNotActive", 57: "InternalLibCurlError",
    58: "UnresolvedHostError", 60: "NotEnoughSpace", 61: "DeviceCorrupted",
    62: "PackageExcludedFromUpdate", 63: "PostInstallMountError", 64: "OverlayfsenabledError",
    65: "UpdateProcessing", 66: "UpdateAlreadyInstalled",
}
# 사용자 취소·이미 설치됨은 설치 실패율에 넣지 않는다
NON_FAILURE_CODES = {0, 48, 66}


def bucket(rollout_id: int | str, device_hash: str) -> int:
    """롤아웃마다 독립적이고 결정적인 버킷 [0, 10000). 비율을 올려도 기존 대상은 유지된다."""
    digest = hashlib.sha256(f"{rollout_id}:{device_hash}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % BUCKETS


def in_rollout(rollout_id: int | str, device_hash: str, percent: float) -> bool:
    if not 0 <= percent <= 100:
        raise ValueError(f"percent out of range: {percent}")
    return bucket(rollout_id, device_hash) < round(percent * BUCKETS / 100)


@dataclass(frozen=True)
class DecodedError:
    raw: int
    base: int
    flags: tuple[str, ...]
    name: str


def decode_error_code(raw: int) -> DecodedError:
    """native ErrorCode(플래그 비트 포함, Java int 로 음수일 수 있음)를 분해한다."""
    value = raw & 0xFFFFFFFF
    base = value & ~SPECIAL_FLAGS_MASK & 0xFFFFFFFF
    flags = tuple(name for bit, name in ERROR_FLAGS.items() if value & bit)
    if base >= OMAHA_HTTP_RESPONSE_BASE:
        name = f"HttpResponse{base - OMAHA_HTTP_RESPONSE_BASE}"
    else:
        name = ERROR_NAMES.get(base, f"ErrorCode{base}")
    return DecodedError(raw, base, flags, name)


def boot_outcome(current_fingerprint: str, source_fingerprint: str, target_fingerprint: str) -> str | None:
    """설치 후 체크인 fingerprint 로 새 슬롯 부팅 성공/이전 슬롯 폴백을 판정한다."""
    if current_fingerprint == target_fingerprint:
        return "boot_success"
    if current_fingerprint == source_fingerprint:
        return "boot_fallback"
    return None  # 다른 빌드 — 판정 불가(수동 조사 대상)


@dataclass
class RolloutWindow:
    """집계 창 동안의 롤아웃 지표."""
    attempted: int                       # 설치를 시작한 기기 수
    failed_by_code: dict[int, int]       # base error code → 기기 수
    installed: int = 0                   # 재부팅 후 판정까지 도달한 기기 수
    boot_fallback: int = 0


@dataclass
class HaltDecision:
    halt: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_halt(window: RolloutWindow, rules: dict) -> HaltDecision:
    """rollout.halt_rules(04-api-spec §2.1) 로 자동 halt 여부를 판단한다. 표본 부족이면 halt 하지 않는다."""
    reasons: list[str] = []
    min_sample = int(rules.get("min_sample", 0))
    if window.attempted >= min_sample and window.attempted > 0:
        failures = sum(n for code, n in window.failed_by_code.items() if code not in NON_FAILURE_CODES)
        rate = failures / window.attempted
        if "max_error_rate" in rules and rate > rules["max_error_rate"]:
            reasons.append(f"error rate {rate:.4f} > {rules['max_error_rate']}")
        for code, limit in rules.get("max_error_code_rate", {}).items():
            code_rate = window.failed_by_code.get(int(code), 0) / window.attempted
            if code_rate > limit:
                name = ERROR_NAMES.get(int(code), f"ErrorCode{code}")
                reasons.append(f"{name}({code}) rate {code_rate:.4f} > {limit}")
    if window.installed >= min_sample and window.installed > 0 and "max_boot_fallback_rate" in rules:
        fallback_rate = window.boot_fallback / window.installed
        if fallback_rate > rules["max_boot_fallback_rate"]:
            reasons.append(f"boot fallback rate {fallback_rate:.4f} > {rules['max_boot_fallback_rate']}")
    return HaltDecision(bool(reasons), reasons)
