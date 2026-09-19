"""플랫폼 프로파일 × 목표 릴리스 → finding 목록 (RD-01, RD-03, RD-04, NF-08).

사실(릴리스·커널·EOL)은 data/releases.json 에, 판정은 아래 규칙 함수에 둔다.
규칙은 공개 1차 출처로 확인된 사실만 blocker 로 판정한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date
from functools import lru_cache
from pathlib import Path

from .kernel import (ABI_MONITOR_SOURCE, KernelModule, branch_key, check_modules, recommended_uprev,
                     uprev_candidates)
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



# finding 문구는 (한국어, English) 쌍으로 만든다. 저장·응답 시 title/detail(ko) 와 title_en/detail_en 으로 나뉜다.
Text = tuple[str, str]


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    title: Text
    detail: Text
    sources: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "severity": self.severity, "title": self.title[0], "detail": self.detail[0],
                "title_en": self.title[1], "detail_en": self.detail[1], "sources": list(self.sources)}


def _plural(n: int, word: str) -> str:
    return word if n == 1 else word + "s"


def _join(*parts: Text) -> Text:
    return "".join(p[0] for p in parts), "".join(p[1] for p in parts)


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


def release_entry(kb: dict, release: str) -> dict:
    for entry in kb["releases"]:
        if entry["release"] == release:
            return entry
    known = ", ".join(r["release"] for r in kb["releases"])
    raise KeyError(f"release {release!r} not in knowledge base ({known})")


def _kernel(kb: dict, branch: str) -> dict | None:
    return next((k for k in kb["kernel_branches"] if k["branch"] == branch), None)


def _uprev_hint(p: PlatformProfile, target: dict, kb: dict, as_of: date) -> Text:
    try:
        best = recommended_uprev(uprev_candidates(kb, target, p.kernel_branch, as_of, p.support_until))
    except KeyError:
        return "", ""
    if best is None or best["is_current"]:
        return "", ""
    short = best["covers_support_until"] is False
    return (f" 권장 uprev 대상: {best['branch']} (EOL {best['eol']}"
            + (" — 제품 지원 종료 목표까지 덮는 브랜치 없음" if short else "") + ").",
            f" Recommended uprev: {best['branch']} (EOL {best['eol']}"
            + (" — no branch covers the product support end date" if short else "") + ").")


def _rule_kernel(p: PlatformProfile, target: dict, kb: dict, as_of: date) -> list[Finding]:
    out: list[Finding] = []
    src = tuple(kb["kernel_sources"])
    k = p.kernel_branch
    kernel = _kernel(kb, k)
    if kernel is None:
        return [Finding("KERNEL_UNKNOWN", "warning",
                        (f"알 수 없는 커널 브랜치 {k}", f"Unknown kernel branch {k}"),
                        ("지식베이스의 ACK 브랜치 목록에 없음. GKI 브랜치명(androidNN-X.Y)을 확인할 것.",
                         "Not in the knowledge base ACK branch list. Check the GKI branch name (androidNN-X.Y)."), src)]
    hint = _uprev_hint(p, target, kb, as_of)
    rel = target["release"]
    if k not in target["supported_kernels"]:
        supported = ", ".join(target["supported_kernels"])
        out.append(Finding("KERNEL_COMPAT", "blocker",
                           (f"{k} 는 Android {rel} 에서 지원되지 않음", f"{k} is not supported on Android {rel}"),
                           _join((f"지원 커널: {supported}. 커널 uprev 필요.",
                                  f"Supported kernels: {supported}. Kernel uprev required."), hint), src))
    else:
        dropped_at = target.get("kernels_unsupported_from", {}).get(k)
        if dropped_at:
            out.append(Finding("KERNEL_COMPAT_QPR", "warning",
                               (f"{k} 는 Android {dropped_at} 부터 지원되지 않음",
                                f"{k} is unsupported from Android {dropped_at}"),
                               _join((f"Android {rel} 는 가능하나 {dropped_at} 이상 업데이트를 하려면 커널 uprev 필요.",
                                      f"Android {rel} works, but updating to {dropped_at} or later requires a kernel "
                                      "uprev."), hint), src))
    eol = date.fromisoformat(kernel["eol"])
    if eol <= as_of:
        out.append(Finding("KERNEL_EOL", "blocker", (f"{k} EOL({eol}) 경과", f"{k} reached EOL ({eol})"),
                           _join(("EOL 커널은 보안 패치·GKI respin 이 제공되지 않음.",
                                  "EOL kernels get no security patches or GKI respins."), hint), src))
    elif p.support_until and eol < p.support_until:
        out.append(Finding("KERNEL_EOL", "warning",
                           (f"{k} EOL({eol}) 이 제품 지원 종료 목표({p.support_until}) 보다 이름",
                            f"{k} EOL ({eol}) is before the product support end date ({p.support_until})"),
                           _join(("지원 기간 중 커널 major 업그레이드 계획이 필요.",
                                  "Plan a major kernel upgrade within the support period."), hint), src))
    return out


MAX_LISTED_SYMBOLS = 20


def _rule_kmi(modules: list[KernelModule], kmi_symbols: set[str], branch: str) -> list[Finding]:
    """vendor 모듈 × 목표 브랜치 KMI symbol list. 최종 판정은 ABI 도구·실제 로드이므로 warning 이하."""
    report = check_modules(modules, kmi_symbols, branch)
    src = (ABI_MONITOR_SOURCE,)
    out = []
    for sym, users in sorted(report.missing.items())[:MAX_LISTED_SYMBOLS]:
        mods = ", ".join(sorted(users))
        out.append(Finding("KMI_SYMBOL_MISSING", "warning",
                           (f"{sym} 가 {branch} KMI symbol list 에 없음", f"{sym} is not in the {branch} KMI symbol list"),
                           (f"사용 모듈: {mods}. vendor symbol list 에 추가 요청하거나 "
                            "해당 심볼 의존을 제거해야 GKI 커널에서 모듈이 로드됨.",
                            f"Used by: {mods}. Request it in the vendor symbol list or drop the dependency, "
                            "otherwise the module will not load on the GKI kernel."), src))
    if len(report.missing) > MAX_LISTED_SYMBOLS:
        rest = sorted(report.missing)[MAX_LISTED_SYMBOLS:]
        listed = ", ".join(rest[:200])
        out.append(Finding("KMI_SYMBOL_MISSING", "warning",
                           (f"그 외 {len(rest)}개 심볼이 {branch} KMI 에 없음",
                            f"{len(rest)} more {_plural(len(rest), 'symbol')} not in the {branch} KMI"), (listed, listed), src))
    if report.rebuild_required:
        n, mods = len(report.rebuild_required), ", ".join(sorted(report.rebuild_required))
        out.append(Finding("KERNEL_MODULE_REBUILD", "info",
                           (f"vendor 모듈 {n}개가 {branch} 이외 브랜치로 빌드됨",
                            f"{n} vendor {_plural(n, 'module')} built for a branch other than {branch}"),
                           (f"vermagic 기준. 목표 브랜치로 재빌드 필요: {mods}",
                            f"Based on vermagic. Rebuild for the target branch: {mods}"), src))
    if report.unknown_vermagic:
        n, mods = len(report.unknown_vermagic), ", ".join(sorted(report.unknown_vermagic))
        out.append(Finding("KERNEL_MODULE_VERMAGIC", "info",
                           (f"vendor 모듈 {n}개의 vermagic 이 GKI 형식이 아님",
                            f"{n} vendor {_plural(n, 'module')} with a non-GKI vermagic"), (mods, mods), src))
    return out


def _rule_vendor(p: PlatformProfile, target: dict, kb: dict) -> list[Finding]:
    out: list[Finding] = []
    if p.uses_ion and target.get("ion_supported") is False:
        out.append(Finding("ION_REMOVED", "blocker", ("ION 사용 — 지원 종료", "Uses ION — no longer supported"),
                           ("ION 지원 커널이 모두 2025-12 EOL. DMA-BUF heaps 로 이전 필요.",
                            "All ION-capable kernels reached EOL in 2025-12. Migrate to DMA-BUF heaps."),
                           (kb["ion_source"],)))
    if p.uses_vndk and target.get("vndk_supported") is False:
        out.append(Finding("VNDK_DEPRECATED", "blocker",
                           ("VNDK 의존 — Android 15+ 에서 폐지", "Depends on VNDK — removed in Android 15+"),
                           ("VNDK 라이브러리를 vendor/product 파티션 일반 라이브러리로 전환, vendor snapshot 사용 중단.",
                            "Move VNDK libraries to regular vendor/product partition libraries and stop using "
                            "vendor snapshots."),
                           tuple(s for s in target["sources"] if "vndk" in s) or tuple(target["sources"])))
    if target.get("requires_sepolicy_memfd") and not p.sepolicy_memfd_ready:
        out.append(Finding("SEPOLICY_MEMFD", "warning",
                           ("sepolicy memfd_class / memfd_file 미대응", "sepolicy lacks memfd_class / memfd_file"),
                           ("Android 17 policy compatibility 조건 해당 launch 기기는 memfd_class capability 필수. "
                            "업그레이드 기기 적용 범위는 확인 필요.",
                            "Android 17 requires the memfd_class capability on launch devices meeting the policy "
                            "compatibility condition. Applicability to upgrading devices is unconfirmed."),
                           tuple(target["sources"][:1])))
    hidl = [h for h in p.hals if h.transport == "hidl"]
    if hidl:
        names = ", ".join(f"{h.name}@{h.version}" for h in hidl)
        out.append(Finding("HIDL_HALS", "warning", (f"HIDL HAL {len(hidl)}개 잔존", f"{len(hidl)} HIDL {_plural(len(hidl), 'HAL')} remaining"),
                           (f"{names}. 릴리스별 HIDL 제거 목록은 공개 요약이 없어 compatibility_matrix XML diff 로 확정 필요.",
                            f"{names}. There is no public per-release list of removed HIDL HALs; confirm with a "
                            "compatibility_matrix XML diff."),
                           ("https://source.android.com/docs/core/architecture/vintf/fcm",)))
    if not p.supports_16kb:
        out.append(Finding("PAGE_16KB", "info", ("16 KB 페이지 미지원", "No 16 KB page support"),
                           ("공개 문서상 기기 선택사항(필수화 여부 미확인). prebuilt .so ELF 정렬·PAGE_SIZE 가정 점검 권장.",
                            "Optional for devices per public docs (whether it becomes mandatory is unconfirmed). "
                            "Check prebuilt .so ELF alignment and PAGE_SIZE assumptions."),
                           (kb["page_size_16kb_source"],)))
    return out


def _rule_fcm(p: PlatformProfile, target: dict) -> list[Finding]:
    levels = target.get("fcm_matrices_in_tree")
    if not p.fcm_target_level or not levels:
        return []
    src = (target["fcm_matrices_source"],)
    if p.fcm_target_level in levels:
        return []
    lv, rel, tree = p.fcm_target_level, target["release"], ", ".join(levels)
    if int(lv) < min(map(int, levels)):
        return [Finding("FCM_LEVEL_REMOVED", "blocker",
                        (f"target FCM level {lv} 매트릭스가 Android {rel} 에서 제거됨",
                         f"Target FCM level {lv} matrix was removed in Android {rel}"),
                        (f"릴리스 소스 트리의 매트릭스 레벨: {tree}. device manifest target-level 상향과 "
                         "해당 레벨 HAL 요구사항 충족 필요.",
                         f"Matrix levels in the release source tree: {tree}. Raise the device manifest "
                         "target-level and meet that level's HAL requirements."), src)]
    return [Finding("FCM_LEVEL_UNKNOWN", "warning",
                    (f"target FCM level {lv} 이 릴리스 트리에 없음", f"Target FCM level {lv} is not in the release tree"),
                    (f"릴리스 소스 트리의 매트릭스 레벨: {tree}.", f"Matrix levels in the release source tree: {tree}."),
                    src)]


MATRIX_ISSUE_SEVERITY = {"NOT_IN_MATRIX": "warning", "VERSION_UNSUPPORTED": "warning",
                         "INSTANCE_NOT_ALLOWED": "info"}


def _rule_manifest(manifest: Manifest, matrix: Matrix) -> list[Finding]:
    """device manifest 를 목표 릴리스 트리의 같은 레벨 matrix 와 비교한다.

    실제 적합성은 check_vintf / vts_treble_vintf 가 최종 판정하므로 warning 이하로만 보고한다.
    """
    out = []
    for issue in check_manifest(manifest, matrix):
        out.append(Finding(f"HAL_{issue.kind}", MATRIX_ISSUE_SEVERITY[issue.kind], (issue.hal, issue.hal),
                           (issue.detail, issue.detail_en),
                           ("https://source.android.com/docs/core/architecture/vintf/comp-matrices",)))
    return out



def evaluate(profile: PlatformProfile, target_release: str, as_of: date,
             kb: dict | None = None, manifest: Manifest | None = None,
             target_matrix: Matrix | None = None, target_kernel_branch: str | None = None,
             kernel_modules: list[KernelModule] | None = None, kmi_symbols: set[str] | None = None) -> dict:
    """readiness_run.summary 형태의 결과를 반환한다.

    manifest 와 target_matrix(목표 릴리스 트리의 매트릭스)를 주면 HAL 단위 비교 결과를 포함한다.
    target_kernel_branch 를 주면 그 커널로 uprev 한 뒤를 기준으로 커널 규칙을 평가하고,
    kernel_modules·kmi_symbols(그 브랜치의 KMI symbol list)를 주면 vendor 모듈 심볼 검사를 포함한다.
    """
    kb = kb or load_kb()
    target = release_entry(kb, target_release)
    if release_key(target_release) <= release_key(profile.android_version):
        raise ValueError(f"target {target_release} is not newer than current {profile.android_version}")
    kernel_profile = profile
    uprev: list[Finding] = []
    if target_kernel_branch and target_kernel_branch != profile.kernel_branch:
        if branch_key(target_kernel_branch) < branch_key(profile.kernel_branch):
            raise ValueError(f"target kernel {target_kernel_branch} is older than current {profile.kernel_branch}")
        kernel_profile = replace(profile, kernel_branch=target_kernel_branch)
        uprev.append(Finding("KERNEL_UPREV_PLANNED", "info",
                             (f"커널 uprev 계획 {profile.kernel_branch} → {target_kernel_branch} 기준으로 판정",
                              f"Evaluated against planned kernel uprev {profile.kernel_branch} → {target_kernel_branch}"),
                             ("vendor 모듈을 목표 브랜치 KMI 기준으로 재빌드하고 vendor symbol list·ABI 검사를 갱신할 것.",
                              "Rebuild vendor modules against the target branch KMI and update the vendor symbol "
                              "list and ABI checks."),
                             tuple(kb["kernel_sources"])))
    findings = (uprev + _rule_kernel(kernel_profile, target, kb, as_of) + _rule_fcm(profile, target)
                + _rule_vendor(profile, target, kb))
    if manifest is not None and target_matrix is not None:
        findings += _rule_manifest(manifest, target_matrix)
    if kernel_modules and kmi_symbols is not None:
        findings += _rule_kmi(kernel_modules, kmi_symbols, kernel_profile.kernel_branch)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id))
    counts = {s: sum(f.severity == s for f in findings) for s in SEVERITY_ORDER}
    return {
        "platform": profile.name,
        "current_release": profile.android_version,
        "target_release": target_release,
        "kernel_branch": kernel_profile.kernel_branch,
        "kb_version": kb["kb_version"],
        "as_of": as_of.isoformat(),
        "ready": counts["blocker"] == 0,
        "counts": counts,
        "findings": [f.to_dict() for f in findings],
    }
