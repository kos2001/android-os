"""OTA 도메인 SQLite 저장소 (P2 패키지 · P3 assignment/이벤트 · P4 롤아웃).

Store 의 커넥션·락·감사 로그를 공유한다. 엔터티는 docs/design/03-data-model.md 와 같다.

assignment 는 (rollout, device) 당 1행이고, 재시도마다 attempt 를 올린다. 설치 결과 지표는 assignment 의
현재 상태가 아니라 attempt 별 이벤트 이력에서 계산한다 — 재시도로 상태가 offered 로 돌아가도
직전 실패·폴백이 자동 halt 입력에서 사라지지 않게 하기 위함이다.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from upgrade_core.matcher import Package, Rollout
from upgrade_core.ota_package import OtaPackageInfo
from upgrade_core.rollout import NON_FAILURE_CODES, RolloutWindow, decode_error_code

from .store import Conflict, NotFound, Store, now
from .fleet import FleetStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS build (
    id INTEGER PRIMARY KEY,
    device TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    incremental TEXT NOT NULL,
    timestamp_utc INTEGER NOT NULL,
    spl TEXT NOT NULL,
    sdk_level INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ota_package (
    id INTEGER PRIMARY KEY,
    target_build_id INTEGER NOT NULL REFERENCES build(id),
    type TEXT NOT NULL CHECK (type IN ('full', 'incremental')),
    pre_device TEXT NOT NULL,                 -- JSON list
    pre_builds TEXT NOT NULL,                 -- JSON list
    post_timestamp INTEGER NOT NULL,
    post_spl TEXT NOT NULL,
    wipe INTEGER NOT NULL,
    downgrade INTEGER NOT NULL,
    spl_downgrade INTEGER NOT NULL,
    url TEXT NOT NULL UNIQUE,
    file_size INTEGER NOT NULL,
    sha256 TEXT,
    payload_offset INTEGER NOT NULL,
    payload_size INTEGER NOT NULL,
    payload_properties TEXT NOT NULL,         -- JSON
    streaming_property_files TEXT NOT NULL,
    payload_metadata TEXT,                    -- JSON {offset,size} | NULL
    status TEXT NOT NULL CHECK (status IN ('ready', 'rejected', 'retired')),
    reject_reasons TEXT NOT NULL,             -- JSON list
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS ota_package_immutable BEFORE UPDATE ON ota_package
WHEN NEW.url IS NOT OLD.url OR NEW.sha256 IS NOT OLD.sha256 OR NEW.payload_properties IS NOT OLD.payload_properties
  OR NEW.payload_offset IS NOT OLD.payload_offset OR NEW.payload_size IS NOT OLD.payload_size
  OR (OLD.status = 'retired' AND NEW.status IS NOT 'retired')
BEGIN
    SELECT RAISE(ABORT, 'ota_package payload fields are immutable');
END;
CREATE TABLE IF NOT EXISTS rollout (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    target_build_id INTEGER NOT NULL REFERENCES build(id),
    channel TEXT NOT NULL CHECK (channel IN ('testing', 'beta', 'stable')),
    filters TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('draft', 'active', 'paused', 'halted', 'completed')),
    current_stage INTEGER NOT NULL DEFAULT 0,  -- 0 = 시작 전
    current_percent REAL NOT NULL DEFAULT 0,
    halt_rules TEXT NOT NULL,
    halt_mode TEXT NOT NULL CHECK (halt_mode IN ('stop_new', 'stop_all_pending')),
    halt_reason TEXT,
    policy TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rollout_stage (
    rollout_id INTEGER NOT NULL REFERENCES rollout(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    percent REAL NOT NULL,
    min_soak_hours REAL NOT NULL,
    promoted_at TEXT,
    promoted_by TEXT,
    PRIMARY KEY (rollout_id, seq)
);
CREATE TABLE IF NOT EXISTS assignment (
    id INTEGER PRIMARY KEY,
    rollout_id INTEGER NOT NULL REFERENCES rollout(id),
    device_hash TEXT NOT NULL,
    package_id INTEGER NOT NULL REFERENCES ota_package(id),
    source_fingerprint TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL CHECK (state IN ('offered', 'downloading', 'installed_pending_reboot',
                                         'boot_success', 'boot_fallback', 'failed')),
    install_boot_id TEXT,                     -- updated_need_reboot 시점의 boot_id
    last_error_code INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (rollout_id, device_hash)
);
CREATE INDEX IF NOT EXISTS assignment_device ON assignment (device_hash);
CREATE TABLE IF NOT EXISTS device_event (
    id INTEGER PRIMARY KEY,
    assignment_id INTEGER REFERENCES assignment(id),
    attempt INTEGER,
    rollout_id INTEGER,
    device_hash TEXT NOT NULL,
    device TEXT,
    type TEXT NOT NULL,
    update_status INTEGER,
    error_code_raw INTEGER,
    error_code_base INTEGER,
    error_flags TEXT,
    fingerprint TEXT,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS device_event_idem ON device_event
    (device_hash, COALESCE(assignment_id, -1), COALESCE(attempt, -1), type, occurred_at) WHERE type <> 'check';
CREATE INDEX IF NOT EXISTS device_event_check ON device_event (device, type, received_at);
CREATE INDEX IF NOT EXISTS device_event_rollout ON device_event (rollout_id, received_at);
"""

STATE_ORDER = {"offered": 0, "downloading": 1, "installed_pending_reboot": 2, "failed": 3,
               "boot_success": 4, "boot_fallback": 4}
BOOT_STATES = ("boot_success", "boot_fallback")
IN_PROGRESS_STATES = ("offered", "downloading", "installed_pending_reboot")
RETRYABLE_STATES = ("failed", "boot_fallback")
USER_CANCELED = 48
ROLLOUT_ACTIONS = {"start": {"draft"}, "promote": {"active"}, "pause": {"active"}, "resume": {"paused"},
                   "halt": {"active", "paused"}, "complete": {"active", "paused", "halted"}}


def _json(v) -> str:
    return json.dumps(v, ensure_ascii=False)


class OtaStore(FleetStore):
    def __init__(self, store: Store):
        self.s = store
        with store.tx() as conn:
            conn.executescript(SCHEMA)
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(rollout_stage)")}
            if "min_successful_boots" not in columns:
                conn.execute("ALTER TABLE rollout_stage ADD COLUMN min_successful_boots INTEGER NOT NULL DEFAULT 0")
            if "min_success_rate" not in columns:
                conn.execute("ALTER TABLE rollout_stage ADD COLUMN min_success_rate REAL")
        self.init_fleet()

    # ------------------------------------------------------------------ builds / packages
    def _ensure_build(self, conn, device: str, fingerprint: str, incremental: str, timestamp: int, spl: str,
                      sdk: int | None) -> int:
        row = conn.execute("SELECT id, timestamp_utc, spl FROM build WHERE fingerprint = ?", (fingerprint,)).fetchone()
        if row:
            if (row["timestamp_utc"], row["spl"]) != (timestamp, spl):
                raise Conflict(f"build {fingerprint} already registered with different timestamp/SPL")
            return row["id"]
        return conn.execute("INSERT INTO build (device, fingerprint, incremental, timestamp_utc, spl, sdk_level, "
                            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (device, fingerprint, incremental, timestamp, spl, sdk, now())).lastrowid

    def register_package(self, url: str, info: OtaPackageInfo, sha256: str | None, actor: str) -> dict:
        if not (info.post_build and info.post_timestamp and info.post_spl and info.pre_device):
            raise Conflict("package metadata lacks pre-device/post-build/timestamp/SPL; cannot register: "
                           + "; ".join(info.reject_reasons))
        status = "ready" if info.ready else "rejected"
        meta = info.payload_metadata
        try:
            with self.s.tx() as conn:
                build_id = self._ensure_build(conn, info.pre_device[0], info.post_build, info.post_build_incremental,
                                              info.post_timestamp, info.post_spl, info.post_sdk_level)
                pid = conn.execute(
                    "INSERT INTO ota_package (target_build_id, type, pre_device, pre_builds, post_timestamp, post_spl, "
                    "wipe, downgrade, spl_downgrade, url, file_size, sha256, payload_offset, payload_size, "
                    "payload_properties, streaming_property_files, payload_metadata, status, reject_reasons, "
                    "created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (build_id, info.package_type, _json(info.pre_device), _json(info.pre_builds), info.post_timestamp,
                     info.post_spl, int(info.wipe), int(info.downgrade), int(info.spl_downgrade), url, info.file_size,
                     sha256 or info.sha256 or None, info.payload_offset, info.payload_size,
                     _json(info.payload_properties), info.streaming_property_files,
                     _json({"offset": meta.offset, "size": meta.size}) if meta else None,
                     status, _json(info.reject_reasons), actor, now())).lastrowid
                self.s._audit(conn, actor, "register", "ota_package", pid,
                              after={"url": url, "status": status, "type": info.package_type,
                                     "post_build": info.post_build, "reject_reasons": info.reject_reasons})
        except sqlite3.IntegrityError as exc:
            raise Conflict(f"package {url} already registered") from exc
        return self.get_package(pid)

    def get_package(self, pid: int) -> dict:
        row = self.s._one("SELECT p.*, b.fingerprint AS post_build, b.device FROM ota_package p "
                          "JOIN build b ON b.id = p.target_build_id WHERE p.id = ?", (pid,))
        return self._package_out(row)

    @staticmethod
    def _package_out(row: dict) -> dict:
        for k in ("pre_device", "pre_builds", "payload_properties", "reject_reasons", "payload_metadata"):
            row[k] = json.loads(row[k]) if row[k] else None
        for k in ("wipe", "downgrade", "spl_downgrade"):
            row[k] = bool(row[k])
        return row

    def list_packages(self, device: str | None = None) -> list[dict]:
        sql = ("SELECT p.*, b.fingerprint AS post_build, b.device FROM ota_package p "
               "JOIN build b ON b.id = p.target_build_id")
        rows = self.s._all(sql + " WHERE b.device = ? ORDER BY p.id", (device,)) if device else \
            self.s._all(sql + " ORDER BY p.id")
        return [self._package_out(r) for r in rows]

    def retire_package(self, pid: int, actor: str) -> dict:
        with self.s.tx() as conn:
            before = self.get_package(pid)
            if before["status"] != "retired":
                conn.execute("UPDATE ota_package SET status = 'retired' WHERE id = ?", (pid,))
                self.s._audit(conn, actor, "retire", "ota_package", pid, before={"status": before["status"]},
                              after={"status": "retired"})
        return self.get_package(pid)

    def build_by_fingerprint(self, fingerprint: str) -> dict:
        return self.s._one("SELECT * FROM build WHERE fingerprint = ?", (fingerprint,))

    # ------------------------------------------------------------------ rollouts
    def create_rollout(self, data: dict, actor: str) -> dict:
        build = self.build_by_fingerprint(data["target_fingerprint"])
        ready = self.s._all("SELECT id FROM ota_package WHERE target_build_id = ? AND status = 'ready'", (build["id"],))
        if not ready:
            raise Conflict(f"no ready package for target build {build['fingerprint']}")
        percents = [s["percent"] for s in data["stages"]]
        if any(b <= a for a, b in zip(percents, percents[1:])):
            raise Conflict("stage percents must be strictly increasing")
        try:
            with self.s.tx() as conn:
                rid = conn.execute(
                    "INSERT INTO rollout (name, target_build_id, channel, filters, state, halt_rules, halt_mode, policy, "
                    "created_by, created_at) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)",
                    (data["name"], build["id"], data["channel"], _json(data["filters"]), _json(data["halt_rules"]),
                     data["halt_mode"], _json(data["policy"]), actor, now())).lastrowid
                for seq, stage in enumerate(data["stages"], 1):
                    conn.execute("INSERT INTO rollout_stage (rollout_id, seq, percent, min_soak_hours, "
                                 "min_successful_boots, min_success_rate) VALUES (?, ?, ?, ?, ?, ?)",
                                 (rid, seq, stage["percent"], stage["min_soak_hours"],
                                  stage.get("min_successful_boots", 0), stage.get("min_success_rate")))
                self.s._audit(conn, actor, "create", "rollout", rid, after=data)
        except sqlite3.IntegrityError as exc:
            raise Conflict(f"rollout {data['name']!r} already exists") from exc
        return self.get_rollout(rid)

    def get_rollout(self, rid: int) -> dict:
        row = self.s._one("SELECT r.*, b.fingerprint AS target_fingerprint, b.device FROM rollout r "
                          "JOIN build b ON b.id = r.target_build_id WHERE r.id = ?", (rid,))
        for k in ("filters", "halt_rules", "policy"):
            row[k] = json.loads(row[k])
        row["stages"] = self.s._all("SELECT seq, percent, min_soak_hours, min_successful_boots, min_success_rate, "
                                    "promoted_at, promoted_by FROM rollout_stage "
                                    "WHERE rollout_id = ? ORDER BY seq", (rid,))
        return row

    def promotion_status(self, rid: int, at: datetime | None = None) -> dict:
        """Conservative rollout-wide attempt history, including failures before retries."""
        at = at or datetime.fromisoformat(now())
        with self.s.tx():
            r = self.get_rollout(rid)
            w = self.rollout_window(rid)
            successes = w.installed - w.boot_fallback
            rate = successes / w.attempted if w.attempted else None
            reasons, soak_until = [], None
            current = r["stages"][r["current_stage"] - 1] if r["current_stage"] else None
            if r["state"] != "active":
                reasons.append("NOT_ACTIVE")
            if r["current_stage"] >= len(r["stages"]):
                reasons.append("FINAL_STAGE")
            if current:
                soak_until = datetime.fromisoformat(current["promoted_at"]) + timedelta(hours=current["min_soak_hours"])
                if at < soak_until:
                    reasons.append("SOAK_PENDING")
                if successes < current["min_successful_boots"]:
                    reasons.append("INSUFFICIENT_SUCCESSFUL_BOOTS")
                threshold = current["min_success_rate"]
                if threshold is not None and (rate is None or rate < threshold):
                    reasons.append("SUCCESS_RATE_BELOW_THRESHOLD")
            return {"rollout_id": rid, "can_promote": not reasons, "reasons": reasons,
                    "soak_until": soak_until.isoformat() if soak_until else None,
                    "attempted": w.attempted, "successful_boots": successes, "success_rate": rate,
                    "min_successful_boots": current["min_successful_boots"] if current else 0,
                    "min_success_rate": current["min_success_rate"] if current else None,
                    "scope": "rollout_all_attempts"}

    def list_rollouts(self) -> list[dict]:
        return [self.get_rollout(r["id"]) for r in self.s._all("SELECT id FROM rollout ORDER BY id")]

    def transition(self, rid: int, action: str, actor: str, reason: str | None = None,
                   at: datetime | None = None) -> dict:
        """start · promote · pause · resume · halt · complete. 읽기와 쓰기를 한 트랜잭션에서 수행한다."""
        at = at or datetime.fromisoformat(now())
        with self.s.tx() as conn:
            r = self.get_rollout(rid)
            state, stage, stages = r["state"], r["current_stage"], r["stages"]
            if state not in ROLLOUT_ACTIONS[action]:
                raise Conflict(f"cannot {action} rollout in state {state}")
            if action in ("start", "promote"):
                if action == "promote":
                    if stage >= len(stages):
                        raise Conflict("already at final stage; use complete")
                    current = stages[stage - 1]
                    soak_until = (datetime.fromisoformat(current["promoted_at"])
                                  + timedelta(hours=current["min_soak_hours"]))
                    if at < soak_until:
                        raise Conflict(f"stage {stage} soak not finished (until {soak_until.isoformat()})")
                    health = self.promotion_status(rid, at)
                    if not health["can_promote"]:
                        raise Conflict("promotion blocked: " + ", ".join(health["reasons"]))
                nxt = stages[stage]
                updates = {"state": "active", "current_stage": nxt["seq"], "current_percent": nxt["percent"]}
            elif action == "halt":
                if not reason:
                    raise Conflict("halt requires a reason")
                updates = {"state": "halted", "halt_reason": reason}
            else:
                updates = {"state": {"pause": "paused", "resume": "active", "complete": "completed"}[action]}
            cur = conn.execute(f"UPDATE rollout SET {', '.join(f'{k} = ?' for k in updates)} "
                               "WHERE id = ? AND state = ?", (*updates.values(), rid, state))
            if cur.rowcount != 1:
                raise Conflict(f"rollout {rid} changed concurrently")
            if action in ("start", "promote"):
                conn.execute("UPDATE rollout_stage SET promoted_at = ?, promoted_by = ? WHERE rollout_id = ? AND seq = ?",
                             (at.isoformat(timespec="seconds"), actor, rid, updates["current_stage"]))
            self.s._audit(conn, actor, action, "rollout", rid,
                          before={"state": state, "current_stage": stage}, after={**updates, "reason": reason})
        return self.get_rollout(rid)

    # ------------------------------------------------------------------ device path
    def candidate_rollouts(self, device: str, channel: str) -> list[dict]:
        """기기 모델·채널이 맞는 active/paused/halted 롤아웃과 ready 패키지 (최신 롤아웃 우선)."""
        rows = self.s._all("SELECT r.id FROM rollout r JOIN build b ON b.id = r.target_build_id "
                           "WHERE b.device = ? AND r.channel = ? AND r.state IN ('active', 'paused', 'halted') "
                           "ORDER BY r.id DESC", (device, channel))
        out = []
        for row in rows:
            out.append(self.rollout_with_packages(row["id"]))
        return out

    def rollout_with_packages(self, rid: int) -> dict:
        r = self.get_rollout(rid)
        pkgs = self.s._all("SELECT p.*, b.fingerprint AS post_build FROM ota_package p JOIN build b "
                           "ON b.id = p.target_build_id WHERE p.target_build_id = ? AND p.status = 'ready'",
                           (r["target_build_id"],))
        r["packages"] = [self._package_out(p) for p in pkgs]
        return r

    @staticmethod
    def to_matcher(r: dict, percent_override: float | None = None, state_override: str | None = None) -> Rollout:
        packages = tuple(Package(p["id"], p["type"], tuple(p["pre_device"]), tuple(p["pre_builds"]), p["post_build"],
                                 p["post_timestamp"], p["post_spl"]) for p in r["packages"])
        return Rollout(r["id"], r["channel"], state_override or r["state"],
                       r["current_percent"] if percent_override is None else percent_override,
                       r["target_fingerprint"], packages, r["filters"])

    def assignments_for(self, device_hash: str) -> list[dict]:
        return self.s._all("SELECT a.*, b.fingerprint AS target_fingerprint FROM assignment a "
                           "JOIN rollout r ON r.id = a.rollout_id JOIN build b ON b.id = r.target_build_id "
                           "WHERE a.device_hash = ?", (device_hash,))

    def get_assignment(self, rollout_id: int, device_hash: str) -> dict | None:
        rows = self.s._all("SELECT * FROM assignment WHERE rollout_id = ? AND device_hash = ?",
                           (rollout_id, device_hash))
        return rows[0] if rows else None

    def upsert_assignment(self, rollout_id: int, device_hash: str, package_id: int, source_fingerprint: str) -> dict:
        """새 할당이면 attempt 1. 직전 시도가 실패/폴백이면 attempt 를 올려 새 시도로 만든다."""
        ts = now()
        with self.s.tx() as conn:
            conn.execute(
                "INSERT INTO assignment (rollout_id, device_hash, package_id, source_fingerprint, state, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, 'offered', ?, ?) "
                "ON CONFLICT(rollout_id, device_hash) DO UPDATE SET package_id = excluded.package_id, "
                "source_fingerprint = excluded.source_fingerprint, updated_at = excluded.updated_at, "
                "attempt = CASE WHEN assignment.state IN ('failed', 'boot_fallback') THEN assignment.attempt + 1 "
                "ELSE assignment.attempt END, "
                "install_boot_id = CASE WHEN assignment.state IN ('failed', 'boot_fallback') THEN NULL "
                "ELSE assignment.install_boot_id END, "
                "state = CASE WHEN assignment.state IN ('failed', 'boot_fallback') THEN 'offered' "
                "ELSE assignment.state END",
                (rollout_id, device_hash, package_id, source_fingerprint, ts, ts))
        return self.get_assignment(rollout_id, device_hash)

    def _set_state(self, conn, aid: int, state: str, error_code: int | None = None, force: bool = False,
                   boot_id: str | None = None) -> None:
        row = conn.execute("SELECT state FROM assignment WHERE id = ?", (aid,)).fetchone()
        if row["state"] in BOOT_STATES and state not in BOOT_STATES:
            return  # 부팅 판정은 해당 attempt 의 최종 상태
        if not force and STATE_ORDER[state] < STATE_ORDER[row["state"]]:
            return
        conn.execute("UPDATE assignment SET state = ?, last_error_code = COALESCE(?, last_error_code), "
                     "install_boot_id = COALESCE(?, install_boot_id), updated_at = ? WHERE id = ?",
                     (state, error_code, boot_id, now(), aid))

    def record_check(self, device_hash: str, device: str, fingerprint: str, payload: dict) -> None:
        with self.s.tx() as conn:
            ts = now()
            conn.execute("INSERT INTO device_event (device_hash, device, type, fingerprint, occurred_at, received_at, "
                         "payload) VALUES (?, ?, 'check', ?, ?, ?, ?)",
                         (device_hash, device, fingerprint, ts, ts, _json(payload)))
            self.save_inventory(conn, device_hash, device, fingerprint, payload, ts)

    def apply_boot_outcomes(self, device_hash: str, fingerprint: str, boot_id: str | None) -> list[dict]:
        """재부팅 후 체크인으로 설치 결과 판정.

        - fingerprint == target → boot_success
        - fingerprint == source 이고 boot_id 가 설치 시점과 다름 → boot_fallback (재부팅했지만 이전 슬롯)
        - boot_id 를 모르면 폴백은 판정하지 않는다 (재부팅 전 체크인과 구별 불가)
        """
        decided = []
        with self.s.tx() as conn:
            for a in self.assignments_for(device_hash):
                if a["state"] != "installed_pending_reboot":
                    continue
                if fingerprint == a["target_fingerprint"]:
                    outcome = "boot_success"
                elif (fingerprint == a["source_fingerprint"] and boot_id and a["install_boot_id"]
                      and boot_id != a["install_boot_id"]):
                    outcome = "boot_fallback"
                else:
                    continue
                self._set_state(conn, a["id"], outcome)
                conn.execute("INSERT INTO device_event (assignment_id, attempt, rollout_id, device_hash, type, "
                             "fingerprint, occurred_at, received_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (a["id"], a["attempt"], a["rollout_id"], device_hash, outcome, fingerprint, now(), now(),
                              _json({"boot_id": boot_id})))
                decided.append({"assignment_id": a["id"], "outcome": outcome})
        return decided

    def record_events(self, device_hash: str, events: list[dict]) -> tuple[int, int]:
        """이벤트 배치를 검증 후 한 트랜잭션으로 저장한다. (accepted, duplicates)."""
        assignments: dict[int, dict] = {}
        for event in events:
            aid = event.get("assignment_id")
            if aid is None:
                continue
            if aid not in assignments:
                rows = self.s._all("SELECT id, device_hash, attempt, rollout_id FROM assignment WHERE id = ?", (aid,))
                if not rows or rows[0]["device_hash"] != device_hash:
                    raise NotFound(f"assignment {aid} for this device")
                assignments[aid] = rows[0]
            if event.get("attempt") is not None and event["attempt"] > assignments[aid]["attempt"]:
                raise Conflict(f"assignment {aid} has no attempt {event['attempt']}")
        accepted = duplicates = 0
        with self.s.tx() as conn:
            for event in events:
                aid = event.get("assignment_id")
                a = assignments.get(aid)
                attempt = event.get("attempt") or (a["attempt"] if a else None)
                decoded = decode_error_code(event["error_code"]) if event.get("error_code") is not None else None
                try:
                    conn.execute(
                        "INSERT INTO device_event (assignment_id, attempt, rollout_id, device_hash, type, update_status, "
                        "error_code_raw, error_code_base, error_flags, fingerprint, occurred_at, received_at, payload) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (aid, attempt, a["rollout_id"] if a else None, device_hash, event["type"],
                         event.get("update_status"), decoded.raw if decoded else None,
                         decoded.base if decoded else None, _json(list(decoded.flags)) if decoded else None,
                         event.get("fingerprint"), event["occurred_at"], now(), _json(event)))
                except sqlite3.IntegrityError:
                    duplicates += 1
                    continue
                accepted += 1
                if a is None or attempt != a["attempt"]:
                    continue  # 이전 attempt 의 늦은 이벤트는 이력에만 남긴다
                kind = event["type"]
                if kind == "download_started":
                    self._set_state(conn, aid, "downloading")
                elif kind == "updated_need_reboot":
                    self._set_state(conn, aid, "installed_pending_reboot", force=True, boot_id=event.get("boot_id"))
                elif kind == "error" and decoded is not None:
                    if decoded.base == USER_CANCELED:
                        self._set_state(conn, aid, "offered", decoded.raw, force=True)
                    elif decoded.base not in NON_FAILURE_CODES:
                        self._set_state(conn, aid, "failed", decoded.raw, force=True)
        return accepted, duplicates

    # ------------------------------------------------------------------ metrics / reports
    def rollout_window(self, rid: int, window_minutes: int | None = None) -> RolloutWindow:
        """attempt 별 이벤트 이력으로 집계한다 (창은 received_at 기준)."""
        args: list = [rid]
        where = "rollout_id = ? AND type <> 'check'"
        if window_minutes:
            where += " AND received_at >= ?"
            args.append((datetime.fromisoformat(now()) - timedelta(minutes=window_minutes)).isoformat(timespec="seconds"))
        rows = self.s._all(f"SELECT assignment_id, attempt, type, error_code_base FROM device_event WHERE {where} "
                           "ORDER BY id", args)
        attempts: dict[tuple[int, int], dict] = {}
        for r in rows:
            a = attempts.setdefault((r["assignment_id"], r["attempt"]),
                                    {"kinds": set(), "last_failure": None, "installed": False})
            a["kinds"].add(r["type"])
            if r["type"] == "error" and r["error_code_base"] is not None:
                if r["error_code_base"] not in NON_FAILURE_CODES and r["error_code_base"] != USER_CANCELED:
                    a["last_failure"] = r["error_code_base"]
                elif r["error_code_base"] == USER_CANCELED:
                    a["last_failure"] = None
        window = RolloutWindow(attempted=0, failed_by_code={})
        for a in attempts.values():
            kinds = a["kinds"]
            booted = kinds & set(BOOT_STATES)
            progressed = kinds & {"download_started", "updated_need_reboot"} or booted
            if not (progressed or a["last_failure"] is not None):
                continue
            window.attempted += 1
            if booted:
                window.installed += 1
                window.boot_fallback += "boot_fallback" in kinds
            elif a["last_failure"] is not None and "updated_need_reboot" not in kinds:
                window.failed_by_code[a["last_failure"]] = window.failed_by_code.get(a["last_failure"], 0) + 1
        return window

    def assignment_counts(self, rid: int) -> dict[str, int]:
        rows = self.s._all("SELECT state, COUNT(*) AS n FROM assignment WHERE rollout_id = ? GROUP BY state", (rid,))
        return {r["state"]: r["n"] for r in rows}

    def delta_candidates(self, target_fingerprint: str, days: int) -> dict:
        build = self.build_by_fingerprint(target_fingerprint)
        since = (datetime.fromisoformat(now()) - timedelta(days=days)).isoformat(timespec="seconds")
        # 기기별 최신 체크인의 fingerprint 만 센다 (창 안에서 업데이트된 기기를 두 번 세지 않음)
        rows = self.s._all(
            "SELECT e.fingerprint, COUNT(*) AS devices FROM device_event e JOIN ("
            "  SELECT device_hash, MAX(id) AS last_id FROM device_event "
            "  WHERE type = 'check' AND device = ? AND received_at >= ? GROUP BY device_hash"
            ") latest ON latest.last_id = e.id WHERE e.fingerprint <> ? "
            "GROUP BY e.fingerprint ORDER BY devices DESC", (build["device"], since, target_fingerprint))
        covered: set[str] = set()
        for p in self.s._all("SELECT pre_builds FROM ota_package WHERE target_build_id = ? AND status = 'ready' "
                             "AND type = 'incremental'", (build["id"],)):
            covered.update(json.loads(p["pre_builds"]))
        total = sum(r["devices"] for r in rows)
        return {
            "target_fingerprint": target_fingerprint, "device": build["device"], "window_days": days,
            "active_devices_not_on_target": total,
            "sources": [{**r, "share": round(r["devices"] / total, 4) if total else 0.0,
                         "has_incremental": r["fingerprint"] in covered} for r in rows],
        }

    # ------------------------------------------------------------------ dashboard
    TIMESERIES_TYPES = ("download_started", "updated_need_reboot", "boot_success")

    def timeseries(self, rid: int, hours: int) -> list[dict]:
        """시간 단위 이벤트 수 (수신 시각 기준). 빈 시간대도 0 으로 채운다."""
        end = datetime.fromisoformat(now()).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=hours - 1)
        rows = self.s._all(
            "SELECT substr(received_at, 1, 13) AS hour, type, COUNT(*) AS n FROM device_event "
            f"WHERE rollout_id = ? AND received_at >= ? AND type IN ({','.join('?' * len(self.TIMESERIES_TYPES))}) "
            "GROUP BY hour, type", (rid, start.isoformat(timespec="seconds"), *self.TIMESERIES_TYPES))
        counts = {(r["hour"], r["type"]): r["n"] for r in rows}
        out = []
        for i in range(hours):
            bucket = start + timedelta(hours=i)
            key = bucket.isoformat(timespec="seconds")[:13]
            out.append({"hour": bucket.isoformat(timespec="seconds"),
                        **{t: counts.get((key, t), 0) for t in self.TIMESERIES_TYPES}})
        return out

    def overview(self) -> dict:
        since = (datetime.fromisoformat(now()) - timedelta(hours=24)).isoformat(timespec="seconds")
        packages = {r["status"]: r["n"] for r in self.s._all(
            "SELECT status, COUNT(*) AS n FROM ota_package GROUP BY status")}
        rollouts = {r["state"]: r["n"] for r in self.s._all("SELECT state, COUNT(*) AS n FROM rollout GROUP BY state")}
        devices = self.s._all("SELECT COUNT(DISTINCT device_hash) AS n FROM device_event "
                              "WHERE type = 'check' AND received_at >= ?", (since,))[0]["n"]
        outcomes = {r["type"]: r["n"] for r in self.s._all(
            "SELECT type, COUNT(*) AS n FROM device_event WHERE received_at >= ? "
            "AND type IN ('boot_success', 'boot_fallback') GROUP BY type", (since,))}
        failures = self.s._all("SELECT COUNT(*) AS n FROM device_event WHERE received_at >= ? AND type = 'error' "
                               "AND error_code_base NOT IN (0, 48, 66)", (since,))[0]["n"]
        return {"packages": packages, "rollouts": rollouts, "devices_checked_in_24h": devices,
                "boot_success_24h": outcomes.get("boot_success", 0),
                "boot_fallback_24h": outcomes.get("boot_fallback", 0), "install_failures_24h": failures}
