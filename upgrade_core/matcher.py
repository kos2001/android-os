"""update-check 매칭 (OT-04, OT-05, OT-13). 04-api-spec §1.1 매칭 절차를 구현한다."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .rollout import in_rollout


@dataclass(frozen=True)
class DeviceState:
    device: str
    fingerprint: str
    build_timestamp: int
    security_patch: str  # YYYY-MM-DD
    channel: str
    device_hash: str
    carrier: str | None = None
    region: str | None = None
    sku: str | None = None
    tags: tuple[str, ...] = ()  # operator-managed groups; never accepted from a device check


@dataclass(frozen=True)
class Package:
    id: int
    type: str  # full | incremental
    pre_device: tuple[str, ...]
    pre_builds: tuple[str, ...]
    post_build: str
    post_timestamp: int
    post_spl: str
    downgrade_approved: bool = False


@dataclass(frozen=True)
class Rollout:
    id: int
    channel: str
    state: str
    percent: float
    target_build: str
    packages: tuple[Package, ...]
    filters: dict = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class Match:
    rollout: Rollout
    package: Package


@dataclass(frozen=True)
class NoMatch:
    reason: str  # UP_TO_DATE | NOT_IN_ROLLOUT | NO_COMPATIBLE_PACKAGE | ROLLOUT_HALTED


FILTER_FIELDS = {"carriers": "carrier", "regions": "region", "skus": "sku", "source_fingerprints": "fingerprint"}
# 우선순위가 낮을수록 먼저 보고한다(여러 롤아웃이 각기 다른 이유로 불일치할 때)
REASON_PRIORITY = ("NO_COMPATIBLE_PACKAGE", "NOT_IN_ROLLOUT", "ROLLOUT_HALTED", "UP_TO_DATE")


def _spl(value: str) -> date:
    return date.fromisoformat(value)


def filters_match(rollout: Rollout, dev: DeviceState) -> bool:
    if rollout.filters.get("tags") and not set(rollout.filters["tags"]).intersection(dev.tags):
        return False
    for key, attr in FILTER_FIELDS.items():
        allowed = rollout.filters.get(key)
        if allowed and getattr(dev, attr) not in allowed:
            return False
    return True


def is_forward_compatible(pkg: Package, dev: DeviceState) -> bool:
    """update_engine 이 거부할 조합(timestamp·SPL 하락)을 서버에서 미리 거른다."""
    if pkg.downgrade_approved:
        return True
    return pkg.post_timestamp > dev.build_timestamp and _spl(pkg.post_spl) >= _spl(dev.security_patch)


def select_package(packages: tuple[Package, ...] | list[Package], dev: DeviceState) -> Package | None:
    """incremental(source fingerprint 정확 일치) 우선, 없으면 full."""
    candidates = [p for p in packages if dev.device in p.pre_device and is_forward_compatible(p, dev)]
    for pkg in candidates:
        if pkg.type == "incremental" and dev.fingerprint in pkg.pre_builds:
            return pkg
    return next((p for p in candidates if p.type == "full"), None)


def select_update(rollouts: list[Rollout], dev: DeviceState) -> Match | NoMatch:
    reasons: set[str] = set()
    for rollout in rollouts:
        if rollout.channel != dev.channel or not filters_match(rollout, dev):
            continue
        if rollout.target_build == dev.fingerprint:
            reasons.add("UP_TO_DATE")
            continue
        if rollout.state == "halted":
            reasons.add("ROLLOUT_HALTED")
            continue
        if rollout.state != "active":
            continue
        if not in_rollout(rollout.id, dev.device_hash, rollout.percent):
            reasons.add("NOT_IN_ROLLOUT")
            continue
        pkg = select_package(rollout.packages, dev)
        if pkg is None:
            reasons.add("NO_COMPATIBLE_PACKAGE")
            continue
        return Match(rollout, pkg)
    reason = next((r for r in REASON_PRIORITY if r in reasons), "UP_TO_DATE")
    return NoMatch(reason)
