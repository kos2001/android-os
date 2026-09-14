"""플랫폼 프로파일 × 목표 릴리스 → finding 목록 (RD-01, RD-03, RD-04, NF-08).

사실(릴리스·커널·EOL)은 data/releases.json 에, 판정은 아래 규칙 함수에 둔다.
규칙은 공개 1차 출처로 확인된 사실만 blocker 로 판정한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from .vintf import Manifest, Matrix, check_manifest

DATA = Path(__file__).resolve().parent / "data" / "releases.json"
SEVERITY_ORDER = {"blocker": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Hal:
    name: str
    transport: str  # hidl | aidl
    version: str


@dataclass
class PlatformProfile:
    name: str
    android_version: str
    kernel_branch: str
    fcm_target_level: str | None = None  # device manifest target-level
    uses_vndk: bool = False
    uses_ion: bool = False
    supports_16kb: bool = False
    sepolicy_memfd_ready: bool = False
    support_until: date | None = None  # 제품 소프트웨어 지원 종료 목표일
    hals: list[Hal] = field(default_factory=list)


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    title: str
    detail: str
    sources: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def load_kb(path: Path = DATA) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def release_key(release: str) -> tuple[int, int]:
    """'17' → (17, 0), '17-QPR1' → (17, 1)."""
    major, _, qpr = release.partition("-QPR")
    try:
        return int(major), int(qpr or 0)
    except ValueError as exc:
        raise ValueError(f"bad release name {release!r} (expected '17' or '17-QPR1')") from exc


def _release(kb: dict, release: str) -> dict:
    for entry in kb["releases"]:
        if entry["release"] == release:
            return entry
    known = ", ".join(r["release"] for r in kb["releases"])
    raise KeyError(f"release {release!r} not in knowledge base ({known})")


def _kernel(kb: dict, branch: str) -> dict | None:
    return next((k for k in kb["kernel_branches"] if k["branch"] == branch), None)


def _rule_kernel(p: PlatformProfile, target: dict, kb: dict, as_of: date) -> list[Finding]:
    out: list[Finding] = []
    src = tuple(kb["kernel_sources"])
    kernel = _kernel(kb, p.kernel_branch)
    if kernel is None:
        return [Finding("KERNEL_UNKNOWN", "warning", f"알 수 없는 커널 브랜치 {p.kernel_branch}",
                        "지식베이스의 ACK 브랜치 목록에 없음. GKI 브랜치명(androidNN-X.Y)을 확인할 것.", src)]
    if p.kernel_branch not in target["supported_kernels"]:
        out.append(Finding("KERNEL_COMPAT", "blocker",
                           f"{p.kernel_branch} 는 Android {target['release']} 에서 지원되지 않음",
                           "지원 커널: " + ", ".join(target["supported_kernels"]) + ". 커널 uprev 필요.", src))
    else:
        dropped_at = target.get("kernels_unsupported_from", {}).get(p.kernel_branch)
        if dropped_at:
            out.append(Finding("KERNEL_COMPAT_QPR", "warning",
                               f"{p.kernel_branch} 는 Android {dropped_at} 부터 지원되지 않음",
                               f"Android {target['release']} 는 가능하나 {dropped_at} 이상 업데이트를 하려면 커널 uprev 필요.",
                               src))
    eol = date.fromisoformat(kernel["eol"])
    if eol <= as_of:
        out.append(Finding("KERNEL_EOL", "blocker", f"{p.kernel_branch} EOL({eol}) 경과",
                           "EOL 커널은 보안 패치·GKI respin 이 제공되지 않음.", src))
    elif p.support_until and eol < p.support_until:
        out.append(Finding("KERNEL_EOL", "warning",
                           f"{p.kernel_branch} EOL({eol}) 이 제품 지원 종료 목표({p.support_until}) 보다 이름",
                           "지원 기간 중 커널 major 업그레이드 계획이 필요.", src))
    return out


def _rule_vendor(p: PlatformProfile, target: dict, kb: dict) -> list[Finding]:
    out: list[Finding] = []
    if p.uses_ion and target.get("ion_supported") is False:
        out.append(Finding("ION_REMOVED", "blocker", "ION 사용 — 지원 종료",
                           "ION 지원 커널이 모두 2025-12 EOL. DMA-BUF heaps 로 이전 필요.", (kb["ion_source"],)))
    if p.uses_vndk and target.get("vndk_supported") is False:
        out.append(Finding("VNDK_DEPRECATED", "blocker", "VNDK 의존 — Android 15+ 에서 폐지",
                           "VNDK 라이브러리를 vendor/product 파티션 일반 라이브러리로 전환, vendor snapshot 사용 중단.",
                           tuple(s for s in target["sources"] if "vndk" in s) or tuple(target["sources"])))
    if target.get("requires_sepolicy_memfd") and not p.sepolicy_memfd_ready:
        out.append(Finding("SEPOLICY_MEMFD", "warning", "sepolicy memfd_class / memfd_file 미대응",
                           "Android 17 policy compatibility 조건 해당 launch 기기는 memfd_class capability 필수. "
                           "업그레이드 기기 적용 범위는 확인 필요.", tuple(target["sources"][:1])))
    hidl = [h for h in p.hals if h.transport == "hidl"]
    if hidl:
        names = ", ".join(f"{h.name}@{h.version}" for h in hidl)
        out.append(Finding("HIDL_HALS", "warning", f"HIDL HAL {len(hidl)}개 잔존",
                           f"{names}. 릴리스별 HIDL 제거 목록은 공개 요약이 없어 compatibility_matrix XML diff 로 확정 필요.",
                           ("https://source.android.com/docs/core/architecture/vintf/fcm",)))
    if not p.supports_16kb:
        out.append(Finding("PAGE_16KB", "info", "16 KB 페이지 미지원",
                           "공개 문서상 기기 선택사항(필수화 여부 미확인). prebuilt .so ELF 정렬·PAGE_SIZE 가정 점검 권장.",
                           (kb["page_size_16kb_source"],)))
    return out


def _rule_fcm(p: PlatformProfile, target: dict) -> list[Finding]:
    levels = target.get("fcm_matrices_in_tree")
    if not p.fcm_target_level or not levels:
        return []
    src = (target["fcm_matrices_source"],)
    if p.fcm_target_level in levels:
        return []
    if int(p.fcm_target_level) < min(map(int, levels)):
        return [Finding("FCM_LEVEL_REMOVED", "blocker",
                        f"target FCM level {p.fcm_target_level} 매트릭스가 Android {target['release']} 에서 제거됨",
                        f"릴리스 소스 트리의 매트릭스 레벨: {', '.join(levels)}. device manifest target-level 상향과 "
                        "해당 레벨 HAL 요구사항 충족 필요.", src)]
    return [Finding("FCM_LEVEL_UNKNOWN", "warning", f"target FCM level {p.fcm_target_level} 이 릴리스 트리에 없음",
                    f"릴리스 소스 트리의 매트릭스 레벨: {', '.join(levels)}.", src)]


MATRIX_ISSUE_SEVERITY = {"NOT_IN_MATRIX": "warning", "VERSION_UNSUPPORTED": "warning",
                         "INSTANCE_NOT_ALLOWED": "info"}


def _rule_manifest(manifest: Manifest, matrix: Matrix) -> list[Finding]:
    """device manifest 를 목표 릴리스 트리의 같은 레벨 matrix 와 비교한다.

    실제 적합성은 check_vintf / vts_treble_vintf 가 최종 판정하므로 warning 이하로만 보고한다.
    """
    out = []
    for issue in check_manifest(manifest, matrix):
        out.append(Finding(f"HAL_{issue.kind}", MATRIX_ISSUE_SEVERITY[issue.kind], issue.hal, issue.detail,
                           ("https://source.android.com/docs/core/architecture/vintf/comp-matrices",)))
    return out


def evaluate(profile: PlatformProfile, target_release: str, as_of: date,
             kb: dict | None = None, manifest: Manifest | None = None,
             target_matrix: Matrix | None = None) -> dict:
    """readiness_run.summary 형태의 결과를 반환한다.

    manifest 와 target_matrix(목표 릴리스 트리의 매트릭스)를 주면 HAL 단위 비교 결과를 포함한다.
    """
    kb = kb or load_kb()
    target = _release(kb, target_release)
    if release_key(target_release) <= release_key(profile.android_version):
        raise ValueError(f"target {target_release} is not newer than current {profile.android_version}")
    findings = (_rule_kernel(profile, target, kb, as_of) + _rule_fcm(profile, target)
                + _rule_vendor(profile, target, kb))
    if manifest is not None and target_matrix is not None:
        findings += _rule_manifest(manifest, target_matrix)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id))
    counts = {s: sum(f.severity == s for f in findings) for s in SEVERITY_ORDER}
    return {
        "platform": profile.name,
        "current_release": profile.android_version,
        "target_release": target_release,
        "kb_version": kb["kb_version"],
        "as_of": as_of.isoformat(),
        "ready": counts["blocker"] == 0,
        "counts": counts,
        "findings": [f.__dict__ | {"sources": list(f.sources)} for f in findings],
    }
