"""드라이버 인벤토리 — 커널 드라이버(vendor .ko)와 사용자 공간 드라이버 인터페이스(HAL)를 서브시스템별로 묶는다.

분류는 추정(heuristic)이다:
- 커널 모듈: import 하는 커널 API 접두사(drm_·snd_·v4l2_ …)로 점수를 매겨 가장 많이 쓰는 서브시스템,
  alias 접두사(of:·pci:·usb:·i2c: …)로 버스를 표시한다.
- HAL: 패키지 이름 `android.hardware.<name>` 의 <name> 으로 매핑한다. vendor HAL 은 other.
판정(blocker/warning)에는 분류 결과를 쓰지 않고, 사실 기반 신호(ION API import 등)만 쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .kernel import KernelArtifactError, KernelModule, parse_kernel_release
from .vintf import HalInstance

SUBSYSTEMS = ("display", "camera", "audio", "wifi", "bluetooth", "input", "usb", "storage", "power", "sensors",
              "gnss", "nfc", "network", "memory", "other")

# 커널 API 접두사 → 서브시스템 (정확한 소속이 아니라 "이 드라이버가 주로 쓰는 커널 프레임워크")
SYMBOL_PREFIXES: dict[str, tuple[str, ...]] = {
    "display": ("drm_", "__drm_", "mipi_dsi_", "backlight_", "dma_fence_"),
    "camera": ("v4l2_", "video_", "vb2_", "media_"),
    "audio": ("snd_", "__snd_"),
    "wifi": ("cfg80211_", "ieee80211_", "wiphy_", "__cfg80211_"),
    "bluetooth": ("hci_", "bt_sock_", "l2cap_"),
    "input": ("input_", "touchscreen_"),
    "usb": ("usb_", "typec_", "__usb_"),
    "storage": ("mmc_", "scsi_", "ufshcd_", "blk_", "sdhci_"),
    "power": ("regulator_", "thermal_", "power_supply_", "devfreq_", "cpufreq_", "pm_genpd_"),
    "sensors": ("iio_", "devm_iio_"),
    "gnss": ("gnss_",),
    "nfc": ("nfc_",),
    "network": ("netif_", "napi_", "register_netdev", "alloc_netdev", "rmnet_"),
    "memory": ("dma_heap_", "ion_", "dma_buf_"),
}

# android.hardware.<name> → 서브시스템
HAL_SUBSYSTEM: dict[str, str] = {
    "camera": "camera", "graphics": "display", "composer": "display", "light": "display",
    "audio": "audio", "soundtrigger": "audio",
    "wifi": "wifi", "bluetooth": "bluetooth", "input": "input", "usb": "usb",
    "sensors": "sensors", "contexthub": "sensors",
    "power": "power", "health": "power", "thermal": "power", "memtrack": "memory",
    "gnss": "gnss", "nfc": "nfc", "secure_element": "nfc",
    "radio": "network", "tetheroffload": "network",
}

BUS_PREFIXES = ("of", "acpi", "pci", "usb", "platform", "i2c", "spi", "sdio", "mhi", "virtio")
# ION 은 모든 Android 버전에서 미지원(ION 지원 커널 2025-12 EOL) — research/01 §2.6
ION_PREFIXES = ("ion_",)


@dataclass
class DriverEntry:
    kind: str  # kernel | hal
    name: str
    subsystem: str
    detail: str | None = None  # 모듈 description 또는 HAL fqname
    buses: list[str] = field(default_factory=list)
    uses_ion: bool = False
    format: str | None = None  # HAL: aidl | hidl | native
    version: str | None = None
    branch: str | None = None  # 모듈 vermagic 브랜치
    license: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def classify_module(module: KernelModule) -> str:
    scores = {s: 0 for s in SYMBOL_PREFIXES}
    for sym in module.undefined:
        for subsystem, prefixes in SYMBOL_PREFIXES.items():
            if sym.startswith(prefixes):
                scores[subsystem] += 1
    # memory(dma-buf) 는 여러 드라이버가 부수적으로 쓰므로 다른 신호가 없을 때만 고른다
    best = max((s for s in scores if s != "memory"), key=lambda s: scores[s])
    if scores[best]:
        return best
    return "memory" if scores["memory"] else "other"


def module_buses(module: KernelModule) -> list[str]:
    return sorted({a.split(":", 1)[0] for a in module.aliases if a.split(":", 1)[0] in BUS_PREFIXES})


def module_uses_ion(module: KernelModule) -> bool:
    return any(sym.startswith(ION_PREFIXES) for sym in module.undefined)


def classify_hal(name: str) -> str:
    parts = name.split(".")
    if len(parts) >= 3 and parts[:2] == ["android", "hardware"]:
        return HAL_SUBSYSTEM.get(parts[2], "other")
    return "other"


def build_inventory(modules: list[KernelModule], hals: list[HalInstance]) -> dict:
    """서브시스템별 {kernel: [...], hal: [...]} 와 합계."""
    entries: list[DriverEntry] = []
    for m in modules:
        try:
            branch = parse_kernel_release(m.kernel_release).branch if m.kernel_release else None
        except KernelArtifactError:
            branch = None
        entries.append(DriverEntry("kernel", m.name, classify_module(m), m.description, module_buses(m),
                                   module_uses_ion(m), branch=branch, license=m.license))
    seen: set[tuple[str, str, str]] = set()
    for h in hals:
        key = (h.format, h.name, str(h.version))
        if key in seen:  # 같은 HAL 의 인스턴스 여러 개는 한 줄로
            continue
        seen.add(key)
        entries.append(DriverEntry("hal", h.name, classify_hal(h.name), h.fqname, format=h.format,
                                   version=str(h.version)))
    groups = {s: {"kernel": [], "hal": []} for s in SUBSYSTEMS}
    for e in entries:
        groups[e.subsystem][e.kind].append(e.to_dict())
    for g in groups.values():
        for items in g.values():
            items.sort(key=lambda d: d["name"])
    subsystems = [{"subsystem": s, **g} for s, g in groups.items() if g["kernel"] or g["hal"]]
    return {
        "subsystems": subsystems,
        "totals": {"kernel": sum(e.kind == "kernel" for e in entries), "hal": sum(e.kind == "hal" for e in entries),
                   "hidl": sum(e.kind == "hal" and e.format == "hidl" for e in entries),
                   "ion_drivers": sorted(e.name for e in entries if e.uses_ion)},
    }
