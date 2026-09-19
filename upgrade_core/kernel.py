"""커널 산출물 분석 — GKI 릴리스 문자열, kernel .config, vendor 모듈(.ko), KMI symbol list, uprev 후보.

- 릴리스 문자열(`uname -r`): GKI 규칙 `<w>.<x>.<y>-<z>-<k>-<something>` (z = androidNN, k = KMI generation)
  https://source.android.com/docs/core/architecture/kernel/gki-versioning
- symbol list(`gki/aarch64/symbols/<vendor>`, android15 이전 `android/abi_gki_aarch64_<vendor>`): GKI 커널은 KMI symbol list 에 있는 심볼만 export 하므로
  vendor 모듈이 쓰는 심볼은 목표 브랜치의 list 에 있어야 한다.
  https://source.android.com/docs/core/architecture/kernel/abi-monitor
- .ko 는 ELF64 little-endian 재배치 파일만 지원한다(arm64·x86_64 GKI). 표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import gzip
import io
import re
import struct
from dataclasses import dataclass, field
from datetime import date

GKI_VERSIONING_SOURCE = "https://source.android.com/docs/core/architecture/kernel/gki-versioning"
ABI_MONITOR_SOURCE = "https://source.android.com/docs/core/architecture/kernel/abi-monitor"

MAX_CONFIG_BYTES = 16 * 1024 * 1024  # 압축 해제 후 상한
BRANCH_RE = re.compile(r"^(android\d+)-(\d+)\.(\d+)$")
RELEASE_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)-(android\d+)-(\d+)(?:-(.+))?$")
CONFIG_SET_RE = re.compile(r"^(CONFIG_[A-Za-z0-9_]+)=(.*)$")
CONFIG_UNSET_RE = re.compile(r"^# (CONFIG_[A-Za-z0-9_]+) is not set$")
SYMBOL_RE = re.compile(r"^[A-Za-z_.$][A-Za-z0-9_.$]*$")


class KernelArtifactError(ValueError):
    """커널 산출물을 해석할 수 없음 (API 에서 422)."""


# --------------------------------------------------------------------------- #
# 브랜치·릴리스 문자열
# --------------------------------------------------------------------------- #
def branch_key(branch: str) -> tuple[int, int, int]:
    """'android14-6.1' → (6, 1, 14). 커널 버전 우선, 같으면 Android 릴리스 순."""
    m = BRANCH_RE.match(branch)
    if not m:
        raise KernelArtifactError(f"bad kernel branch {branch!r} (expected androidNN-X.Y)")
    return int(m.group(2)), int(m.group(3)), int(m.group(1)[len("android"):])


@dataclass(frozen=True)
class KernelRelease:
    raw: str
    version: tuple[int, int, int]
    android_release: str  # android14
    kmi_generation: int
    suffix: str | None

    @property
    def branch(self) -> str:
        return f"{self.android_release}-{self.version[0]}.{self.version[1]}"


def parse_kernel_release(text: str) -> KernelRelease:
    """`uname -r` 또는 vermagic 첫 토큰을 GKI 규칙으로 해석한다. 비 GKI 형식은 거부한다."""
    raw = text.strip()
    m = RELEASE_RE.match(raw)
    if not m:
        raise KernelArtifactError(
            f"kernel release {raw!r} is not in GKI form <w>.<x>.<y>-<androidNN>-<kmi_generation>[-...]")
    return KernelRelease(raw, (int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4), int(m.group(5)),
                         m.group(6))


# --------------------------------------------------------------------------- #
# kernel .config
# --------------------------------------------------------------------------- #
def read_config_bytes(data: bytes) -> str:
    """.config 텍스트 또는 /proc/config.gz 를 받아 텍스트로 돌려준다."""
    if data[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                data = gz.read(MAX_CONFIG_BYTES + 1)
        except (OSError, EOFError) as exc:
            raise KernelArtifactError(f"config.gz unreadable: {exc}") from exc
    if len(data) > MAX_CONFIG_BYTES:
        raise KernelArtifactError(f"kernel config larger than {MAX_CONFIG_BYTES} bytes")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KernelArtifactError("kernel config is not UTF-8 text") from exc


def parse_kconfig(text: str) -> dict[str, str]:
    """CONFIG_X → 값('y', 'm', '"str"', 숫자). `# CONFIG_X is not set` 는 'n'."""
    options: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if m := CONFIG_SET_RE.match(line):
            options[m.group(1)] = m.group(2)
        elif m := CONFIG_UNSET_RE.match(line):
            options[m.group(1)] = "n"
    if not options:
        raise KernelArtifactError("no CONFIG_ options found (not a kernel .config?)")
    return options


def _enabled(options: dict[str, str], name: str) -> bool:
    return options.get(name, "n") in ("y", "m")


def config_hints(options: dict[str, str]) -> dict:
    """플랫폼 프로파일에 반영할 수 있는 사실만 뽑는다."""
    page_kb = 16 if _enabled(options, "CONFIG_ARM64_16K_PAGES") else \
        64 if _enabled(options, "CONFIG_ARM64_64K_PAGES") else \
        4 if _enabled(options, "CONFIG_ARM64_4K_PAGES") else None
    return {
        "uses_ion": _enabled(options, "CONFIG_ION"),
        "supports_16kb": page_kb == 16,
        "page_size_kb": page_kb,
        "dmabuf_heaps": _enabled(options, "CONFIG_DMABUF_HEAPS"),
        "modversions": _enabled(options, "CONFIG_MODVERSIONS"),
    }


# --------------------------------------------------------------------------- #
# vendor 모듈 (.ko)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class KernelModule:
    filename: str
    name: str
    vermagic: str | None
    license: str | None
    depends: tuple[str, ...]
    undefined: tuple[str, ...]  # 모듈이 가져다 쓰는 심볼
    exports: tuple[str, ...]  # EXPORT_SYMBOL* 로 내보내는 심볼
    description: str | None = None  # MODULE_DESCRIPTION
    aliases: tuple[str, ...] = ()  # MODULE_DEVICE_TABLE 이 만든 alias (of:, pci:, usb:, platform: …)

    @property
    def kernel_release(self) -> str | None:
        return self.vermagic.split()[0] if self.vermagic else None

    def to_dict(self) -> dict:
        return {"filename": self.filename, "name": self.name, "vermagic": self.vermagic, "license": self.license,
                "depends": list(self.depends), "undefined": list(self.undefined), "exports": list(self.exports),
                "description": self.description, "aliases": list(self.aliases)}

    @classmethod
    def from_dict(cls, d: dict) -> "KernelModule":
        return cls(d["filename"], d["name"], d.get("vermagic"), d.get("license"), tuple(d.get("depends", ())),
                   tuple(d.get("undefined", ())), tuple(d.get("exports", ())), d.get("description"),
                   tuple(d.get("aliases", ())))


ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
SECTION_HEADER = struct.Struct("<IIQQQQIIQQ")
SYMBOL = struct.Struct("<IBBHQQ")
ET_REL, SHT_SYMTAB, SHN_UNDEF = 1, 2, 0
STB_GLOBAL, STB_WEAK = 1, 2
KSYMTAB_PREFIX = "__ksymtab_"
MAX_ALIASES = 200
NOT_EXPORTS = {"__ksymtab_strings"}


def _cstr(blob: bytes, offset: int) -> str:
    end = blob.find(b"\0", offset)
    return blob[offset:end if end >= 0 else len(blob)].decode("utf-8", "replace")


def inspect_module(data: bytes, filename: str = "module.ko") -> KernelModule:
    """.ko 의 .modinfo·심볼 테이블을 읽는다. 로드 가능 여부는 판정하지 않는다."""
    if len(data) < ELF_HEADER.size or data[:4] != b"\x7fELF":
        raise KernelArtifactError(f"{filename}: not an ELF file")
    if data[4] != 2 or data[5] != 1:
        raise KernelArtifactError(f"{filename}: only ELF64 little-endian modules are supported")
    (_, e_type, _, _, _, _, e_shoff, _, _, _, _, e_shentsize, e_shnum, e_shstrndx) = ELF_HEADER.unpack_from(data)
    if e_type != ET_REL:
        raise KernelArtifactError(f"{filename}: not a relocatable object (kernel modules are ET_REL)")
    if e_shentsize != SECTION_HEADER.size or e_shstrndx >= e_shnum or \
            e_shoff + e_shnum * SECTION_HEADER.size > len(data):
        raise KernelArtifactError(f"{filename}: malformed section header table")

    sections = [SECTION_HEADER.unpack_from(data, e_shoff + i * SECTION_HEADER.size) for i in range(e_shnum)]

    def body(index: int) -> bytes:
        _, sh_type, _, _, offset, size, *_ = sections[index]
        if sh_type == 8:  # SHT_NOBITS
            return b""
        if offset + size > len(data):
            raise KernelArtifactError(f"{filename}: section {index} exceeds file size")
        return data[offset:offset + size]

    shstr = body(e_shstrndx)
    names = [_cstr(shstr, s[0]) for s in sections]

    modinfo: dict[str, list[str]] = {}
    if ".modinfo" in names:
        for entry in body(names.index(".modinfo")).split(b"\0"):
            key, sep, value = entry.decode("utf-8", "replace").partition("=")
            if sep:
                modinfo.setdefault(key, []).append(value)

    undefined: set[str] = set()
    exports: set[str] = set()
    for i, (_, sh_type, _, _, _, _, sh_link, _, _, sh_entsize) in enumerate(sections):
        if sh_type != SHT_SYMTAB:
            continue
        if sh_entsize != SYMBOL.size or sh_link >= e_shnum:
            raise KernelArtifactError(f"{filename}: malformed symbol table")
        table, strtab = body(i), body(sh_link)
        for off in range(SYMBOL.size, len(table) - SYMBOL.size + 1, SYMBOL.size):  # 0번은 null 심볼
            st_name, st_info, _, st_shndx, _, _ = SYMBOL.unpack_from(table, off)
            if not st_name:
                continue
            name = _cstr(strtab, st_name)
            if st_shndx == SHN_UNDEF and st_info >> 4 in (STB_GLOBAL, STB_WEAK):
                undefined.add(name)
            elif name.startswith(KSYMTAB_PREFIX) and name not in NOT_EXPORTS:
                exports.add(name[len(KSYMTAB_PREFIX):])

    stem = filename.rsplit("/", 1)[-1].removesuffix(".ko")
    depends = tuple(d for d in ",".join(modinfo.get("depends", [])).split(",") if d)
    return KernelModule(filename, (modinfo.get("name") or [stem])[0], (modinfo.get("vermagic") or [None])[0],
                        (modinfo.get("license") or [None])[0], depends, tuple(sorted(undefined)),
                        tuple(sorted(exports)), (modinfo.get("description") or [None])[0],
                        tuple(modinfo.get("alias", [])[:MAX_ALIASES]))


# --------------------------------------------------------------------------- #
# KMI symbol list
# --------------------------------------------------------------------------- #
def parse_symbol_list(text: str) -> set[str]:
    """`android/abi_gki_aarch64*`·`gki/aarch64/symbols/*` 형식: `[section]` 헤더, `#` 주석, 줄마다 심볼 하나.

    vendor 파일은 비어 있을 수 있다(실제 android16-6.12 `meizu`). 전체가 비었는지는 호출자가 판단한다.
    """
    symbols: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line or (line.startswith("[") and line.endswith("]")):
            continue
        if not SYMBOL_RE.match(line):
            raise KernelArtifactError(f"line {lineno}: {line[:60]!r} is not a symbol name")
        symbols.add(line)
    return symbols


@dataclass
class KmiReport:
    target_branch: str
    modules: int
    missing: dict[str, list[str]] = field(default_factory=dict)  # 심볼 → 사용하는 모듈
    rebuild_required: list[str] = field(default_factory=list)  # vermagic 브랜치 ≠ 목표 브랜치
    unknown_vermagic: list[str] = field(default_factory=list)


def check_modules(modules: list[KernelModule], kmi_symbols: set[str], target_branch: str) -> KmiReport:
    """vendor 모듈이 가져다 쓰는 심볼 중 (목표 KMI symbol list ∪ 다른 vendor 모듈 export) 에 없는 것을 찾는다.

    GKI 모듈(system_dlkm)이 export 하는 심볼은 알 수 없으므로 누락으로 보일 수 있다 — 결과는 warning 으로만 쓴다.
    """
    provided = {sym for m in modules for sym in m.exports}
    report = KmiReport(target_branch, len(modules))
    for m in modules:
        for sym in m.undefined:
            if sym not in kmi_symbols and sym not in provided:
                report.missing.setdefault(sym, []).append(m.name)
        release = m.kernel_release
        try:
            branch = parse_kernel_release(release).branch if release else None
        except KernelArtifactError:
            branch = None
        if branch is None:
            report.unknown_vermagic.append(m.name)
        elif branch != target_branch:
            report.rebuild_required.append(m.name)
    return report


# --------------------------------------------------------------------------- #
# uprev 후보
# --------------------------------------------------------------------------- #
def uprev_candidates(kb: dict, target: dict, current_branch: str, as_of: date,
                     support_until: date | None = None) -> list[dict]:
    """목표 릴리스에서 지원되는 브랜치 중 현재 커널보다 오래되지 않은 것 (최신 우선).

    같은 커널 버전(예: android13-5.15 → android14-5.15)은 KMI 가 다른 브랜치이므로 uprev 로 포함한다.
    """
    current = branch_key(current_branch)
    eols = {k["branch"]: k["eol"] for k in kb["kernel_branches"]}
    dropped = target.get("kernels_unsupported_from", {})
    out = []
    for branch in target["supported_kernels"]:
        if branch_key(branch) < current:
            continue
        eol = date.fromisoformat(eols[branch])
        out.append({
            "branch": branch,
            "eol": eol.isoformat(),
            "is_current": branch == current_branch,
            "eol_passed": eol <= as_of,
            "covers_support_until": None if support_until is None else eol >= support_until,
            "unsupported_from": dropped.get(branch),
        })
    out.sort(key=lambda c: branch_key(c["branch"]), reverse=True)
    return out


def recommended_uprev(candidates: list[dict]) -> dict | None:
    """EOL 전·QPR 에서도 유지되는 후보 중 지원 기간을 덮는 가장 작은 변경(가장 오래된 브랜치).

    지원 기간을 덮는 후보가 없으면 EOL 이 가장 늦은 후보 (covers_support_until=False 로 드러난다).
    """
    ok = [c for c in candidates if not c["eol_passed"] and not c["unsupported_from"]]
    covering = [c for c in ok if c["covers_support_until"] is not False]
    if covering:
        return min(covering, key=lambda c: branch_key(c["branch"]))
    return max(ok, key=lambda c: (c["eol"], branch_key(c["branch"]))) if ok else None
