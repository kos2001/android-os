"""VINTF manifest / compatibility matrix 파싱·비교 (RD-02, RD-07).

- device manifest(+ vintf_fragments) → HAL 인스턴스 목록
- framework compatibility matrix 두 레벨 diff → 추가/제거/버전 범위 변경 HAL
- device manifest × matrix → matrix 에 없는 HAL, 최소 버전 미달 HAL, 허용되지 않은 인스턴스

버전 호환 규칙은 libvintf VersionRange::supportedBy 와 같다:
`majorVer == ver.majorVer && minMinor <= ver.minorVer` (상한은 검사하지 않음).
HIDL·native 는 `major.minor`, AIDL 은 major 가 없으므로 major 를 0 으로 두고 버전 정수를 minor 로 취급한다.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

AIDL_DEFAULT_VERSION = 1


class VintfError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}" if self.major else str(self.minor)


@dataclass(frozen=True)
class VersionRange:
    major: int
    min_minor: int
    max_minor: int

    def supported_by(self, v: Version) -> bool:
        return self.major == v.major and self.min_minor <= v.minor

    def __str__(self) -> str:
        head = f"{self.major}." if self.major else ""
        tail = f"-{self.max_minor}" if self.max_minor != self.min_minor else ""
        return f"{head}{self.min_minor}{tail}"


@dataclass(frozen=True)
class HalInstance:
    format: str  # aidl | hidl | native
    name: str
    version: Version
    interface: str
    instance: str

    @property
    def fqname(self) -> str:
        return f"{self.name}@{self.version}::{self.interface}/{self.instance}"


@dataclass
class Manifest:
    target_level: str | None
    hals: list[HalInstance] = field(default_factory=list)


@dataclass(frozen=True)
class MatrixInterface:
    name: str
    instances: tuple[str, ...]
    regex_instances: tuple[str, ...]

    def allows(self, instance: str) -> bool:
        return instance in self.instances or any(re.fullmatch(r, instance) for r in self.regex_instances)


@dataclass
class MatrixHal:
    format: str
    name: str
    versions: list[VersionRange]
    interfaces: dict[str, MatrixInterface]
    optional: bool
    updatable_via_apex: bool


@dataclass
class Matrix:
    level: str
    hals: dict[tuple[str, str], MatrixHal]


def _text(el: ET.Element, tag: str) -> str | None:
    child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _parse_version(fmt: str, text: str) -> Version:
    try:
        if "." in text:  # hidl · native (major.minor)
            major, minor = text.split(".")
            return Version(int(major), int(minor))
        return Version(0, int(text))
    except ValueError as exc:
        raise VintfError(f"bad {fmt} version {text!r}") from exc


def _parse_range(fmt: str, text: str) -> VersionRange:
    try:
        if "." in text:  # hidl · native (major.minor[-maxminor])
            major, minors = text.split(".")
            lo, _, hi = minors.partition("-")
            return VersionRange(int(major), int(lo), int(hi or lo))
        lo, _, hi = text.partition("-")
        return VersionRange(0, int(lo), int(hi or lo))
    except ValueError as exc:
        raise VintfError(f"bad {fmt} version range {text!r}") from exc


def _root(xml: str | bytes, expected: str) -> ET.Element:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise VintfError(f"invalid XML: {exc}") from exc
    if root.tag != expected:
        raise VintfError(f"expected <{expected}>, got <{root.tag}>")
    return root


def parse_manifest(*documents: str | bytes) -> Manifest:
    """device manifest 와 fragment 들을 합친다. target-level 은 선언한 문서에서 가져온다."""
    manifest = Manifest(target_level=None)
    seen: set[HalInstance] = set()
    for doc in documents:
        root = _root(doc, "manifest")
        if root.get("type", "device") != "device":
            raise VintfError(f"expected device manifest, got type={root.get('type')}")
        level = root.get("target-level")
        if level:
            if manifest.target_level and manifest.target_level != level:
                raise VintfError(f"conflicting target-level {manifest.target_level} vs {level}")
            manifest.target_level = level
        for hal in root.findall("hal"):
            for inst in _manifest_hal_instances(hal):
                if inst not in seen:
                    seen.add(inst)
                    manifest.hals.append(inst)
    return manifest


def _manifest_hal_instances(hal: ET.Element) -> list[HalInstance]:
    fmt = hal.get("format", "hidl")
    name = _text(hal, "name")
    if not name:
        raise VintfError("<hal> without <name>")
    versions = [_parse_version(fmt, v.text.strip()) for v in hal.findall("version") if v.text]
    if not versions:
        versions = [Version(0, AIDL_DEFAULT_VERSION)] if fmt == "aidl" else []
    out: list[HalInstance] = []
    for iface in hal.findall("interface"):
        iname = _text(iface, "name") or ""
        for inst in iface.findall("instance"):
            out.extend(HalInstance(fmt, name, v, iname, (inst.text or "").strip()) for v in versions)
    for fq in hal.findall("fqname"):
        text = (fq.text or "").strip()
        # hidl: @2.4::IComposer/default · aidl: IHealth/default
        match = re.fullmatch(r"(?:@(?P<ver>[\d.]+)::)?(?P<iface>[\w.]+)/(?P<inst>.+)", text)
        if not match:
            raise VintfError(f"bad fqname {text!r} in {name}")
        fq_versions = [_parse_version(fmt, match["ver"])] if match["ver"] else versions
        out.extend(HalInstance(fmt, name, v, match["iface"], match["inst"]) for v in fq_versions)
    if not out and fmt != "native":
        raise VintfError(f"{name}: no interface instances declared")
    return out


def parse_matrix(xml: str | bytes) -> Matrix:
    root = _root(xml, "compatibility-matrix")
    if root.get("type") != "framework":
        raise VintfError(f"expected framework matrix, got type={root.get('type')}")
    level = root.get("level")
    if not level:
        raise VintfError("framework matrix without level")
    hals: dict[tuple[str, str], MatrixHal] = {}
    for hal in root.findall("hal"):
        fmt = hal.get("format", "hidl")
        name = _text(hal, "name")
        if not name:
            raise VintfError("<hal> without <name>")
        ranges = [_parse_range(fmt, v.text.strip()) for v in hal.findall("version") if v.text]
        if not ranges and fmt == "aidl":
            ranges = [VersionRange(0, AIDL_DEFAULT_VERSION, AIDL_DEFAULT_VERSION)]
        interfaces = {}
        for iface in hal.findall("interface"):
            iname = _text(iface, "name") or ""
            interfaces[iname] = MatrixInterface(
                iname,
                tuple((i.text or "").strip() for i in iface.findall("instance")),
                tuple((i.text or "").strip() for i in iface.findall("regex-instance")),
            )
        key = (fmt, name)
        if key in hals:  # 같은 HAL 이 여러 번 나오면 합친다
            hals[key].versions.extend(ranges)
            hals[key].interfaces.update(interfaces)
        else:
            hals[key] = MatrixHal(fmt, name, ranges, interfaces, hal.get("optional") == "true",
                                  hal.get("updatable-via-apex") == "true")
    return Matrix(level, hals)


@dataclass
class MatrixDiff:
    old_level: str
    new_level: str
    added: list[str]
    removed: list[str]
    changed: list[dict]


def diff_matrices(old: Matrix, new: Matrix) -> MatrixDiff:
    label = lambda key: f"{key[1]} ({key[0]})"  # noqa: E731
    added = sorted(label(k) for k in new.hals.keys() - old.hals.keys())
    removed = sorted(label(k) for k in old.hals.keys() - new.hals.keys())
    changed = []
    for key in sorted(old.hals.keys() & new.hals.keys(), key=lambda k: (k[1], k[0])):
        before = sorted(map(str, old.hals[key].versions))
        after = sorted(map(str, new.hals[key].versions))
        added_ifaces = sorted(new.hals[key].interfaces.keys() - old.hals[key].interfaces.keys())
        removed_ifaces = sorted(old.hals[key].interfaces.keys() - new.hals[key].interfaces.keys())
        if before != after or added_ifaces or removed_ifaces:
            changed.append({"hal": label(key), "versions_before": before, "versions_after": after,
                            "interfaces_added": added_ifaces, "interfaces_removed": removed_ifaces})
    return MatrixDiff(old.level, new.level, added, removed, changed)


@dataclass(frozen=True)
class CompatIssue:
    kind: str  # NOT_IN_MATRIX | VERSION_UNSUPPORTED | INSTANCE_NOT_ALLOWED
    hal: str
    detail: str


def check_manifest(manifest: Manifest, matrix: Matrix) -> list[CompatIssue]:
    issues: list[CompatIssue] = []
    for inst in manifest.hals:
        if inst.format == "native":
            continue
        mhal = matrix.hals.get((inst.format, inst.name))
        if mhal is None:
            issues.append(CompatIssue("NOT_IN_MATRIX", inst.fqname,
                                      f"framework matrix level {matrix.level} 에 {inst.format} {inst.name} 없음"))
            continue
        if not any(r.supported_by(inst.version) for r in mhal.versions):
            allowed = ", ".join(map(str, mhal.versions))
            issues.append(CompatIssue("VERSION_UNSUPPORTED", inst.fqname,
                                      f"버전 {inst.version} 은 level {matrix.level} 허용 범위({allowed}) 미달/불일치"))
            continue
        iface = mhal.interfaces.get(inst.interface)
        if mhal.interfaces and (iface is None or not iface.allows(inst.instance)):
            issues.append(CompatIssue("INSTANCE_NOT_ALLOWED", inst.fqname,
                                      f"level {matrix.level} 에 {inst.interface}/{inst.instance} 선언 없음"))
    return issues
