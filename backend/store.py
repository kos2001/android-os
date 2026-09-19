"""SQLite 저장소 (개발·P1). 운영 스키마는 docs/design/schema.sql(PostgreSQL) 와 같은 엔터티를 따른다.

JSON 컬럼은 TEXT 로 저장한다. 모든 쓰기는 한 커넥션 + 락으로 직렬화한다.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS platform (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    soc TEXT NOT NULL,
    android_version TEXT NOT NULL,
    kernel_branch TEXT NOT NULL,
    fcm_target_level TEXT,
    uses_vndk INTEGER NOT NULL DEFAULT 0,
    uses_ion INTEGER NOT NULL DEFAULT 0,
    supports_16kb INTEGER NOT NULL DEFAULT 0,
    sepolicy_memfd_ready INTEGER NOT NULL DEFAULT 0,
    support_until TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_manifest (
    platform_id INTEGER PRIMARY KEY REFERENCES platform(id) ON DELETE CASCADE,
    documents TEXT NOT NULL,          -- JSON [{filename, xml}]
    target_level TEXT,
    hal_count INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fcm_matrix (
    release TEXT NOT NULL,
    level TEXT NOT NULL,
    xml TEXT NOT NULL,
    source TEXT,
    uploaded_at TEXT NOT NULL,
    PRIMARY KEY (release, level)
);
CREATE TABLE IF NOT EXISTS readiness_run (
    id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platform(id) ON DELETE CASCADE,
    target_release TEXT NOT NULL,
    kb_version TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS finding (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES readiness_run(id) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('blocker', 'warning', 'info')),
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    title_en TEXT,                    -- NULL: 영어 문구 도입 전 판정
    detail_en TEXT,
    sources TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_item (
    id INTEGER PRIMARY KEY,
    finding_id INTEGER NOT NULL UNIQUE REFERENCES finding(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'done', 'waived')),
    owner TEXT,
    waive_reason TEXT,
    external_ref TEXT,
    updated_at TEXT NOT NULL,
    CHECK (status <> 'waived' OR waive_reason IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS platform_kernel (
    platform_id INTEGER PRIMARY KEY REFERENCES platform(id) ON DELETE CASCADE,
    kernel_release TEXT,              -- uname -r
    kmi_generation INTEGER,
    config TEXT,                      -- JSON {CONFIG_X: value}
    modules TEXT,                     -- JSON [KernelModule.to_dict()]
    uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kmi_symbol_list (
    branch TEXT PRIMARY KEY,          -- 'android17-6.18'
    symbols TEXT NOT NULL,            -- JSON [name]
    files TEXT NOT NULL,              -- JSON [filename]
    source TEXT,
    uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id INTEGER,
    before TEXT,
    after TEXT,
    at TEXT NOT NULL
);
"""

BOOL_COLUMNS = ("uses_vndk", "uses_ion", "supports_16kb", "sepolicy_memfd_ready")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._lock = threading.RLock()

    def _migrate(self) -> None:
        """CREATE TABLE IF NOT EXISTS 는 기존 테이블에 컬럼을 추가하지 않으므로 여기서 보강한다."""
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(finding)")}
        for column in ("title_en", "detail_en"):
            if column not in columns:
                self._conn.execute(f"ALTER TABLE finding ADD COLUMN {column} TEXT")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def _one(self, sql: str, args=()) -> dict:
        with self._lock:
            row = self._conn.execute(sql, args).fetchone()
        if row is None:
            raise NotFound(sql.split("FROM", 1)[1].split()[0])
        return dict(row)

    def _all(self, sql: str, args=()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    @staticmethod
    def _audit(conn, actor, action, entity, entity_id, before=None, after=None) -> None:
        conn.execute("INSERT INTO audit_log (actor, action, entity, entity_id, before, after, at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (actor, action, entity, entity_id, json.dumps(before, ensure_ascii=False) if before else None,
                      json.dumps(after, ensure_ascii=False) if after else None, now()))

    # ------------------------------------------------------------------ platform
    def create_platform(self, data: dict, actor: str) -> dict:
        cols = ["name", "soc", "android_version", "kernel_branch", "fcm_target_level", *BOOL_COLUMNS, "support_until"]
        values = [int(data[c]) if c in BOOL_COLUMNS else data.get(c) for c in cols]
        try:
            with self.tx() as conn:
                cur = conn.execute(f"INSERT INTO platform ({', '.join(cols)}, created_at) "
                                   f"VALUES ({', '.join('?' * len(cols))}, ?)", (*values, now()))
                self._audit(conn, actor, "create", "platform", cur.lastrowid, after=data)
        except sqlite3.IntegrityError as exc:
            raise Conflict(f"platform {data['name']!r} already exists") from exc
        return self.get_platform(cur.lastrowid)

    def get_platform(self, pid: int) -> dict:
        row = self._one("SELECT * FROM platform WHERE id = ?", (pid,))
        for c in BOOL_COLUMNS:
            row[c] = bool(row[c])
        manifest = self._all("SELECT target_level, hal_count, uploaded_at FROM platform_manifest WHERE platform_id = ?",
                             (pid,))
        row["manifest"] = manifest[0] if manifest else None
        kernel = self._all("SELECT kernel_release, kmi_generation, config IS NOT NULL AS has_config, modules, "
                           "uploaded_at FROM platform_kernel WHERE platform_id = ?", (pid,))
        if kernel:
            k = kernel[0]
            row["kernel"] = {"kernel_release": k["kernel_release"], "kmi_generation": k["kmi_generation"],
                             "has_config": bool(k["has_config"]),
                             "module_count": len(json.loads(k["modules"])) if k["modules"] else 0,
                             "uploaded_at": k["uploaded_at"]}
        else:
            row["kernel"] = None
        return row

    def list_platforms(self) -> list[dict]:
        return [self.get_platform(r["id"]) for r in self._all("SELECT id FROM platform ORDER BY id")]

    def save_manifest(self, pid: int, documents: list[dict], target_level: str | None, hal_count: int,
                      actor: str) -> dict:
        before = self.get_platform(pid)
        with self.tx() as conn:
            conn.execute("INSERT INTO platform_manifest (platform_id, documents, target_level, hal_count, uploaded_at) "
                         "VALUES (?, ?, ?, ?, ?) ON CONFLICT(platform_id) DO UPDATE SET documents = excluded.documents, "
                         "target_level = excluded.target_level, hal_count = excluded.hal_count, "
                         "uploaded_at = excluded.uploaded_at",
                         (pid, json.dumps(documents, ensure_ascii=False), target_level, hal_count, now()))
            if target_level and target_level != before["fcm_target_level"]:
                conn.execute("UPDATE platform SET fcm_target_level = ? WHERE id = ?", (target_level, pid))
            self._audit(conn, actor, "upload_manifest", "platform", pid,
                        before={"fcm_target_level": before["fcm_target_level"]},
                        after={"fcm_target_level": target_level, "hal_count": hal_count,
                               "files": [d["filename"] for d in documents]})
        return self.get_platform(pid)

    def manifest_documents(self, pid: int) -> list[dict] | None:
        rows = self._all("SELECT documents FROM platform_manifest WHERE platform_id = ?", (pid,))
        return json.loads(rows[0]["documents"]) if rows else None

    # ------------------------------------------------------------------ kernel
    def save_kernel(self, pid: int, changes: dict, profile_updates: dict, actor: str) -> dict:
        """주어진 항목(kernel_release·kmi_generation / config / modules)만 교체하고 나머지는 유지한다."""
        before = self.get_platform(pid)
        stored = {k: (json.dumps(v, ensure_ascii=False) if k in ("config", "modules") else v)
                  for k, v in changes.items()}
        cols = list(stored)
        with self.tx() as conn:
            conn.execute(f"INSERT INTO platform_kernel (platform_id, {', '.join(cols)}, uploaded_at) "
                         f"VALUES (?, {', '.join('?' * len(cols))}, ?) ON CONFLICT(platform_id) DO UPDATE SET "
                         + ", ".join(f"{c} = excluded.{c}" for c in [*cols, "uploaded_at"]),
                         (pid, *stored.values(), now()))
            updates = {k: v for k, v in profile_updates.items() if before[k] != v}
            for column, value in updates.items():
                conn.execute(f"UPDATE platform SET {column} = ? WHERE id = ?", (int(value), pid))
            self._audit(conn, actor, "upload_kernel", "platform", pid,
                        before={k: before[k] for k in updates} or None,
                        after={"kernel_release": changes.get("kernel_release"),
                               "config": "config" in changes,
                               "modules": [m["name"] for m in changes.get("modules", [])], **updates})
        return self.get_platform(pid)

    def kernel_artifacts(self, pid: int) -> dict | None:
        rows = self._all("SELECT kernel_release, kmi_generation, config, modules, uploaded_at FROM platform_kernel "
                         "WHERE platform_id = ?", (pid,))
        if not rows:
            return None
        row = rows[0]
        return {**row, "config": json.loads(row["config"]) if row["config"] else None,
                "modules": json.loads(row["modules"]) if row["modules"] else []}

    def save_symbol_list(self, branch: str, symbols: set[str], files: list[str], source: str | None,
                         actor: str) -> dict:
        with self.tx() as conn:
            conn.execute("INSERT INTO kmi_symbol_list (branch, symbols, files, source, uploaded_at) "
                         "VALUES (?, ?, ?, ?, ?) ON CONFLICT(branch) DO UPDATE SET symbols = excluded.symbols, "
                         "files = excluded.files, source = excluded.source, uploaded_at = excluded.uploaded_at",
                         (branch, json.dumps(sorted(symbols)), json.dumps(files), source, now()))
            self._audit(conn, actor, "upload_symbol_list", "kmi_symbol_list", None,
                        after={"branch": branch, "symbols": len(symbols), "files": files, "source": source})
        return {"branch": branch, "symbol_count": len(symbols), "files": files, "source": source}

    def symbol_list(self, branch: str) -> set[str] | None:
        rows = self._all("SELECT symbols FROM kmi_symbol_list WHERE branch = ?", (branch,))
        return set(json.loads(rows[0]["symbols"])) if rows else None

    def list_symbol_lists(self) -> list[dict]:
        rows = self._all("SELECT branch, symbols, files, source, uploaded_at FROM kmi_symbol_list ORDER BY branch")
        return [{"branch": r["branch"], "symbol_count": len(json.loads(r["symbols"])), "files": json.loads(r["files"]),
                 "source": r["source"], "uploaded_at": r["uploaded_at"]} for r in rows]

    # ------------------------------------------------------------------ matrices
    def save_matrix(self, release: str, level: str, xml: str, source: str | None, actor: str) -> dict:
        with self.tx() as conn:
            conn.execute("INSERT INTO fcm_matrix (release, level, xml, source, uploaded_at) VALUES (?, ?, ?, ?, ?) "
                         "ON CONFLICT(release, level) DO UPDATE SET xml = excluded.xml, source = excluded.source, "
                         "uploaded_at = excluded.uploaded_at", (release, level, xml, source, now()))
            self._audit(conn, actor, "upload_matrix", "fcm_matrix", None, after={"release": release, "level": level,
                                                                                  "source": source})
        return {"release": release, "level": level, "source": source}

    def get_matrix_xml(self, release: str, level: str) -> str | None:
        rows = self._all("SELECT xml FROM fcm_matrix WHERE release = ? AND level = ?", (release, level))
        return rows[0]["xml"] if rows else None

    def list_matrices(self) -> list[dict]:
        return self._all("SELECT release, level, source, uploaded_at FROM fcm_matrix ORDER BY release, level")

    # ------------------------------------------------------------------ readiness
    def save_run(self, pid: int, summary: dict, actor: str) -> dict:
        with self.tx() as conn:
            cur = conn.execute("INSERT INTO readiness_run (platform_id, target_release, kb_version, summary, created_by, "
                               "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                               (pid, summary["target_release"], summary["kb_version"],
                                json.dumps(summary, ensure_ascii=False), actor, now()))
            run_id = cur.lastrowid
            for f in summary["findings"]:
                fid = conn.execute("INSERT INTO finding (run_id, rule_id, severity, title, detail, title_en, detail_en, "
                                   "sources) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (run_id, f["rule_id"], f["severity"], f["title"], f["detail"], f.get("title_en"),
                                    f.get("detail_en"), json.dumps(f["sources"]))).lastrowid
                if f["severity"] != "info":
                    conn.execute("INSERT INTO work_item (finding_id, updated_at) VALUES (?, ?)", (fid, now()))
            self._audit(conn, actor, "create", "readiness_run", run_id,
                        after={"platform_id": pid, "target_release": summary["target_release"],
                               "counts": summary["counts"]})
        return self.get_run(run_id)

    def get_run(self, run_id: int) -> dict:
        run = self._one("SELECT * FROM readiness_run WHERE id = ?", (run_id,))
        summary = json.loads(run.pop("summary"))
        findings = self._all(
            "SELECT f.id, f.rule_id, f.severity, f.title, f.detail, f.title_en, f.detail_en, f.sources, w.id AS work_item_id, "
            "w.status, w.owner, w.waive_reason, w.external_ref FROM finding f "
            "LEFT JOIN work_item w ON w.finding_id = f.id WHERE f.run_id = ? ORDER BY f.id", (run_id,))
        for f in findings:
            f["sources"] = json.loads(f["sources"])
        return {**run, "ready": summary["ready"], "counts": summary["counts"], "as_of": summary["as_of"],
                "current_release": summary["current_release"], "kernel_branch": summary.get("kernel_branch"),
                "findings": findings}

    def list_runs(self, pid: int) -> list[dict]:
        return self._all("SELECT id, target_release, kb_version, created_by, created_at FROM readiness_run "
                         "WHERE platform_id = ? ORDER BY id DESC", (pid,))

    def update_work_item(self, item_id: int, changes: dict, actor: str) -> dict:
        before = self._one("SELECT * FROM work_item WHERE id = ?", (item_id,))
        merged = {**before, **changes}
        if merged["status"] == "waived" and not merged.get("waive_reason"):
            raise Conflict("waived work items require waive_reason")
        if merged["status"] != "waived":
            merged["waive_reason"] = None
        with self.tx() as conn:
            conn.execute("UPDATE work_item SET status = ?, owner = ?, waive_reason = ?, external_ref = ?, updated_at = ? "
                         "WHERE id = ?", (merged["status"], merged["owner"], merged["waive_reason"],
                                          merged["external_ref"], now(), item_id))
            self._audit(conn, actor, "update", "work_item", item_id, before=before, after=changes)
        return self._one("SELECT * FROM work_item WHERE id = ?", (item_id,))

    def audit(self, entity: str | None = None, limit: int = 100) -> list[dict]:
        if entity:
            return self._all("SELECT * FROM audit_log WHERE entity = ? ORDER BY id DESC LIMIT ?", (entity, limit))
        return self._all("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))

    def readiness_overview(self) -> dict:
        platforms = self._all("SELECT id, name, soc, android_version, kernel_branch FROM platform ORDER BY name")
        latest = {r["platform_id"]: r for r in self._all(
            "SELECT r.platform_id, r.id, r.target_release, r.summary, r.created_at FROM readiness_run r "
            "JOIN (SELECT platform_id, MAX(id) AS id FROM readiness_run GROUP BY platform_id) m ON m.id = r.id")}
        open_items = {r["severity"]: r["n"] for r in self._all(
            "SELECT f.severity, COUNT(*) AS n FROM work_item w JOIN finding f ON f.id = w.finding_id "
            "JOIN (SELECT platform_id, MAX(id) AS id FROM readiness_run GROUP BY platform_id) m ON m.id = f.run_id "
            "WHERE w.status IN ('todo', 'in_progress') GROUP BY f.severity")}
        rows = []
        for p in platforms:
            run = latest.get(p["id"])
            summary = json.loads(run["summary"]) if run else None
            rows.append({**p, "latest_run": None if not run else {
                "id": run["id"], "target_release": run["target_release"], "created_at": run["created_at"],
                "ready": summary["ready"], "counts": summary["counts"]}})
        return {"platforms": rows, "open_work_items": open_items}
