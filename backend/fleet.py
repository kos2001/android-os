"""Latest device inventory and operator-owned tags, derived from update checks."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .store import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS fleet_device (
    device_hash TEXT PRIMARY KEY,
    device TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    channel TEXT NOT NULL,
    inventory TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fleet_device_seen ON fleet_device(last_seen_at, device_hash);
CREATE INDEX IF NOT EXISTS fleet_device_model ON fleet_device(device, channel);
CREATE TABLE IF NOT EXISTS device_tag (
    device_hash TEXT NOT NULL REFERENCES fleet_device(device_hash) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (device_hash, tag)
);
CREATE INDEX IF NOT EXISTS device_tag_name ON device_tag(tag, device_hash);
"""


class FleetStore:
    def init_fleet(self):
        with self.s.tx() as conn:
            conn.executescript(SCHEMA)
            # Only run the history backfill once, including databases with no checks yet.
            conn.execute("CREATE TABLE IF NOT EXISTS ota_migration (name TEXT PRIMARY KEY)")
            if not conn.execute("SELECT 1 FROM ota_migration WHERE name = 'fleet-v1'").fetchone():
                conn.execute(
                    "INSERT OR IGNORE INTO fleet_device "
                    "SELECT e.device_hash, e.device, e.fingerprint, "
                    "COALESCE(json_extract(e.payload, '$.channel'), 'stable'), e.payload, "
                    "latest.first_seen, e.received_at FROM device_event e JOIN "
                    "(SELECT device_hash, MAX(id) AS last_id, MIN(received_at) AS first_seen "
                    "FROM device_event WHERE type = 'check' GROUP BY device_hash) latest "
                    "ON latest.last_id = e.id")
                conn.execute("INSERT INTO ota_migration VALUES ('fleet-v1')")

    @staticmethod
    def save_inventory(conn, device_hash: str, device: str, fingerprint: str, payload: dict, ts: str):
        conn.execute(
            "INSERT INTO fleet_device VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(device_hash) DO UPDATE SET device = excluded.device, "
            "fingerprint = excluded.fingerprint, channel = excluded.channel, "
            "inventory = excluded.inventory, last_seen_at = excluded.last_seen_at",
            (device_hash, device, fingerprint, payload.get("channel", "stable"),
             json.dumps(payload, ensure_ascii=False), ts, ts))

    def device_tags(self, device_hash: str) -> tuple[str, ...]:
        return tuple(r["tag"] for r in self.s._all(
            "SELECT tag FROM device_tag WHERE device_hash = ? ORDER BY tag", (device_hash,)))

    def _inventory_out(self, rows: list[dict]) -> list[dict]:
        if not rows:
            return []
        tags = self.s._all(
            f"SELECT device_hash, tag FROM device_tag WHERE device_hash IN ({','.join('?' for _ in rows)}) "
            "ORDER BY tag", [r["device_hash"] for r in rows])
        by_hash: dict[str, list[str]] = {}
        for tag in tags:
            by_hash.setdefault(tag["device_hash"], []).append(tag["tag"])
        for row in rows:
            inventory = json.loads(row.pop("inventory"))
            row.update({k: inventory.get(k) for k in (
                "build_timestamp", "security_patch", "sdk_level", "carrier", "region", "sku")})
            row["tags"] = by_hash.get(row["device_hash"], [])
        return rows

    def list_devices(self, *, q: str = "", device: str | None = None, channel: str | None = None,
                     tag: str | None = None, seen_within_hours: int | None = None,
                     limit: int = 50, offset: int = 0) -> dict:
        where, args = ["1 = 1"], []
        for col, value in (("device", device), ("channel", channel)):
            if value:
                where.append(f"d.{col} = ?")
                args.append(value)
        if q:
            where.append("instr(lower(d.device_hash || ' ' || d.device || ' ' || d.fingerprint), lower(?)) > 0")
            args.append(q)
        if tag:
            where.append("EXISTS (SELECT 1 FROM device_tag t WHERE t.device_hash = d.device_hash AND t.tag = ?)")
            args.append(tag)
        if seen_within_hours is not None:
            where.append("d.last_seen_at >= ?")
            args.append((datetime.fromisoformat(now()) - timedelta(hours=seen_within_hours)).isoformat(timespec="seconds"))
        clause = " AND ".join(where)
        with self.s.tx():
            total = self.s._one(f"SELECT COUNT(*) AS n FROM fleet_device d WHERE {clause}", args)["n"]
            rows = self.s._all(f"SELECT d.* FROM fleet_device d WHERE {clause} "
                               "ORDER BY d.last_seen_at DESC, d.device_hash LIMIT ? OFFSET ?", (*args, limit, offset))
            return {"items": self._inventory_out(rows), "total": total, "limit": limit, "offset": offset}

    def get_device(self, device_hash: str) -> dict:
        with self.s.tx():
            row = self.s._one("SELECT * FROM fleet_device WHERE device_hash = ?", (device_hash,))
            return {**self._inventory_out([row])[0], "assignments": self.assignments_for(device_hash)}

    def set_device_tags(self, device_hash: str, tags: list[str], actor: str) -> dict:
        tags = sorted(set(tags))
        with self.s.tx() as conn:
            before = self.get_device(device_hash)
            conn.execute("DELETE FROM device_tag WHERE device_hash = ?", (device_hash,))
            conn.executemany("INSERT INTO device_tag VALUES (?, ?)", [(device_hash, tag) for tag in tags])
            if before["tags"] != tags:
                self.s._audit(conn, actor, "set_tags", "device", None,
                              before={"device_hash": device_hash, "tags": before["tags"]},
                              after={"device_hash": device_hash, "tags": tags})
        return self.get_device(device_hash)

    def fleet_summary(self) -> dict:
        cutoff = (datetime.fromisoformat(now()) - timedelta(hours=24)).isoformat(timespec="seconds")
        with self.s.tx():
            counts = self.s._one("SELECT COUNT(*) AS total, COALESCE(SUM(last_seen_at >= ?), 0) AS seen_24h "
                                 "FROM fleet_device", (cutoff,))
            return {**counts, "models": self.s._all(
                "SELECT device, COUNT(*) AS devices FROM fleet_device GROUP BY device ORDER BY device"),
                "tags": self.s._all("SELECT tag, COUNT(*) AS devices FROM device_tag GROUP BY tag ORDER BY tag")}
