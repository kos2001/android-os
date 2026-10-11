"""Fleet targeting, read-only previews and promotion gates on real API flows."""
import io
import json
import unittest
from datetime import datetime, timedelta, timezone

from tests import test_ota_api as flow
from upgrade_core.rollout import in_rollout

if flow.TestClient is not None:
    from backend.app import create_app
    from backend.ota_store import OtaStore, SCHEMA
    from backend.store import Store


@unittest.skipIf(flow.TestClient is None, "fastapi not installed (use .venv)")
class FleetTests(unittest.TestCase):
    setUp = flow.OtaFlowTests.setUp
    register_all = flow.OtaFlowTests.register_all
    rollout = flow.OtaFlowTests.rollout
    events = flow.OtaFlowTests.events

    def check(self, name, **kw):
        response = self.client.post("/device/v1/update-check", json=flow.check_body(flow.dhash(name), **kw))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def tags(self, name, tags):
        response = self.client.put(f"/admin/v1/devices/{flow.dhash(name)}/tags", json={"tags": tags})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_latest_inventory_filters_pagination_and_tags_survive_check(self):
        self.check("a", region="KR", carrier="SKT")
        self.tags("a", ["lab", "canary", "lab"])
        self.check("a", fingerprint=flow.DST, security_patch="2026-07-05", region="US")
        self.check("b", channel="beta")
        c = self.client
        self.assertEqual(c.get("/admin/v1/devices").json()["total"], 2)
        filtered = c.get("/admin/v1/devices?tag=canary&channel=stable").json()
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["tags"], ["canary", "lab"])
        self.assertEqual(filtered["items"][0]["region"], "US")
        self.assertEqual(filtered["items"][0]["fingerprint"], flow.DST)
        page1 = c.get("/admin/v1/devices?limit=1").json()
        page2 = c.get("/admin/v1/devices?limit=1&offset=1").json()
        self.assertNotEqual(page1["items"][0]["device_hash"], page2["items"][0]["device_hash"])
        self.assertEqual(c.get(f"/admin/v1/devices?q={flow.dhash('a')[:12]}").json()["total"], 1)
        self.assertEqual(c.get("/admin/v1/devices?q=%25").json()["total"], 0)  # literal, not SQL wildcard
        summary = c.get("/admin/v1/devices/summary").json()
        self.assertEqual((summary["total"], summary["seen_24h"]), (2, 2))
        self.assertEqual(summary["tags"], [{"tag": "canary", "devices": 1}, {"tag": "lab", "devices": 1}])
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with self.store.tx() as conn:
            conn.execute("UPDATE fleet_device SET last_seen_at = ? WHERE device_hash = ?", (old, flow.dhash("b")))
        self.assertEqual(c.get("/admin/v1/devices?seen_within_hours=24").json()["total"], 1)

    def test_tag_validation_audit_and_rbac(self):
        self.check("a")
        c = self.client
        path = f"/admin/v1/devices/{flow.dhash('a')}/tags"
        for tags in (["bad tag"], ["a" * 33], [""] , [f"tag-{i}" for i in range(21)]):
            self.assertEqual(c.put(path, json={"tags": tags}).status_code, 422)
        self.assertEqual(c.put(f"/admin/v1/devices/{flow.dhash('missing')}/tags", json={"tags": []}).status_code, 404)
        self.tags("a", ["canary", "canary"])
        self.tags("a", ["canary"])
        audit = c.get("/admin/v1/audit?entity=device").json()
        self.assertEqual(len(audit), 1)
        self.assertEqual(json.loads(audit[0]["after"])["device_hash"], flow.dhash("a"))
        secure = flow.TestClient(create_app(store=self.store, api_keys="v:reader:viewer,o:ops:operator",
                    device_keys="device-secret", package_opener=lambda _: io.BytesIO(b""), auto_halt_interval_s=0))
        self.assertEqual(secure.get("/admin/v1/devices").status_code, 401)
        self.assertEqual(secure.get("/admin/v1/devices", headers={"Authorization": "Bearer v"}).status_code, 200)
        self.assertEqual(secure.put(path, json={"tags": []}, headers={"Authorization": "Bearer v"}).status_code, 403)
        self.assertEqual(secure.put(path, json={"tags": []}, headers={"Authorization": "Bearer device-secret"}).status_code, 401)
        self.assertEqual(secure.put(path, json={"tags": []}, headers={"Authorization": "Bearer o"}).status_code, 200)
        for query in ("limit=0", "limit=201", "offset=-1", "seen_within_hours=0", "channel=other"):
            self.assertEqual(c.get(f"/admin/v1/devices?{query}").status_code, 422)
        self.assertEqual(c.get("/admin/v1/devices/bad-hash").status_code, 422)

    def test_any_tag_targeting_spoof_prevention_and_in_progress_continuity(self):
        self.register_all()
        self.check("a")
        self.check("b")
        self.tags("a", ["canary"])
        self.tags("b", ["lab"])
        rid = self.rollout(filters={"tags": ["canary", "lab"]})["id"]
        self.client.post(f"/admin/v1/rollouts/{rid}/start")
        a = self.check("a")
        self.assertTrue(a["update_available"])
        self.assertTrue(self.check("b")["update_available"])
        self.assertEqual(self.check("spoof", tags=["canary"])["reason"], "FILTER_MISMATCH")
        self.assertEqual(self.client.get(f"/admin/v1/devices/{flow.dhash('spoof')}").json()["tags"], [])
        self.tags("a", [])
        self.assertEqual(self.check("a")["assignment_id"], a["assignment_id"])
        self.client.post(f"/admin/v1/rollouts/{rid}/pause")
        self.assertTrue(self.check("a")["update_available"])
        self.check("new")
        self.tags("new", ["canary"])
        self.assertFalse(self.check("new")["update_available"])
        self.client.post(f"/admin/v1/rollouts/{rid}/halt", json={"reason": "test"})
        self.assertTrue(self.check("a")["update_available"])
        self.assertEqual(self.check("new")["reason"], "ROLLOUT_HALTED")

    def test_preview_read_only_matches_real_offers_and_stable_percentage(self):
        self.register_all()
        for name, kw in [("delta", {}), ("full", {"fingerprint": flow.OLD}), ("filtered", {}),
                         ("target", {"fingerprint": flow.DST}), ("incompatible", {"build_timestamp": 9_999_999_999}),
                         ("beta", {"channel": "beta"})]:
            self.check(name, **kw)
            if name != "filtered":
                self.tags(name, ["canary"])
        rid = self.rollout(filters={"tags": ["canary"]},
                           stages=[{"percent": 99, "min_soak_hours": 0}, {"percent": 100, "min_soak_hours": 0}])["id"]
        tables = ("assignment", "device_event", "audit_log", "fleet_device")
        before = [self.store._all(f"SELECT * FROM {table}") for table in tables]
        preview = self.client.get(f"/admin/v1/rollouts/{rid}/preview").json()
        self.assertEqual(preview["mode"], "draft_first_stage")
        self.assertEqual(preview["total"], 5)  # other channel excluded
        self.assertEqual(preview["reasons"]["FILTER_MISMATCH"], 1)
        self.assertEqual(preview["reasons"]["UP_TO_DATE"], 1)
        self.assertEqual(sum(preview["reasons"].values()), 5)
        self.assertEqual(before, [self.store._all(f"SELECT * FROM {table}") for table in tables])
        self.client.post(f"/admin/v1/rollouts/{rid}/start")
        for name in ("delta", "full"):
            offered = self.check(name, **({"fingerprint": flow.OLD} if name == "full" else {}))
            expected = in_rollout(rid, flow.dhash(name), 99)
            self.assertEqual(offered["update_available"], expected)
            if expected:
                self.assertEqual(offered["package"]["type"], "full" if name == "full" else "incremental")
        self.assertEqual(preview["eligible"], sum(in_rollout(rid, flow.dhash(name), 99) for name in ("delta", "full")))

    def test_preview_pending_reboot_retry_limit_and_halt_modes(self):
        self.register_all()
        rid = self.rollout(policy={"max_attempts": 1}, halt_mode="stop_all_pending")["id"]
        self.client.post(f"/admin/v1/rollouts/{rid}/start")
        a, b = self.check("pending"), self.check("failed")
        self.events(flow.dhash("pending"), {"assignment_id": a["assignment_id"], "type": "updated_need_reboot",
                                             "occurred_at": flow.ts(), "boot_id": flow.B1})
        self.events(flow.dhash("failed"), {"assignment_id": b["assignment_id"], "type": "error", "error_code": 9,
                                            "occurred_at": flow.ts()})
        preview = self.client.get(f"/admin/v1/rollouts/{rid}/preview").json()
        self.assertEqual(preview["reasons"], {"PENDING_REBOOT": 1, "RETRY_LIMIT_REACHED": 1})
        self.assertEqual(self.check("pending", boot_id=flow.B1)["reason"], "PENDING_REBOOT")
        self.assertEqual(self.check("failed")["reason"], "RETRY_LIMIT_REACHED")
        self.client.post(f"/admin/v1/rollouts/{rid}/halt", json={"reason": "test"})
        preview = self.client.get(f"/admin/v1/rollouts/{rid}/preview").json()
        self.assertEqual(preview["reasons"], {"ROLLOUT_HALTED": 2})

    def test_promotion_requires_successful_boots_and_retains_retry_failures(self):
        self.register_all()
        rid = self.rollout(stages=[{"percent": 99, "min_soak_hours": 0, "min_successful_boots": 2,
                                    "min_success_rate": 0.6}, {"percent": 100, "min_soak_hours": 0}])["id"]
        self.client.post(f"/admin/v1/rollouts/{rid}/start")
        status_url = f"/admin/v1/rollouts/{rid}/promotion-status"
        promote_url = f"/admin/v1/rollouts/{rid}/promote"
        status = self.client.get(status_url).json()
        self.assertFalse(status["can_promote"])
        self.assertIn("INSUFFICIENT_SUCCESSFUL_BOOTS", status["reasons"])
        self.assertEqual(self.client.post(promote_url).status_code, 409)
        names = [f"success-{i}" for i in range(10) if in_rollout(rid, flow.dhash(f"success-{i}"), 99)][:2]
        first, second = (self.check(name) for name in names)
        self.events(flow.dhash(names[0]), {"assignment_id": first["assignment_id"], "type": "updated_need_reboot", "occurred_at": flow.ts()})
        # Installation alone does not satisfy a successful-boot gate.
        self.assertEqual(self.client.get(status_url).json()["successful_boots"], 0)
        self.check(names[0], fingerprint=flow.DST)
        self.events(flow.dhash(names[1]), {"assignment_id": second["assignment_id"], "attempt": 1,
                    "type": "error", "error_code": 9, "occurred_at": flow.ts()})
        self.assertEqual(self.client.post(promote_url).status_code, 409)
        retry = self.check(names[1])
        self.assertEqual(retry["attempt"], 2)
        self.events(flow.dhash(names[1]), {"assignment_id": second["assignment_id"], "attempt": 2,
                    "type": "updated_need_reboot", "occurred_at": flow.ts(10)})
        self.check(names[1], fingerprint=flow.DST)
        status = self.client.get(status_url).json()
        self.assertEqual((status["successful_boots"], status["attempted"]), (2, 3))
        self.assertAlmostEqual(status["success_rate"], 2 / 3)
        self.assertTrue(status["can_promote"])
        self.assertEqual(self.client.post(promote_url).status_code, 200)
        self.assertIn("FINAL_STAGE", self.client.get(status_url).json()["reasons"])

    def test_gate_validation_soak_and_legacy_defaults(self):
        self.register_all()
        body = {"name": "bad", "target_fingerprint": flow.DST, "channel": "stable"}
        for stage in ({"percent": 10, "min_success_rate": 1.1}, {"percent": 10, "min_successful_boots": -1}):
            self.assertEqual(self.client.post("/admin/v1/rollouts", json={**body, "stages": [stage]}).status_code, 422)
        r = self.rollout(stages=[{"percent": 50, "min_soak_hours": 24}, {"percent": 100, "min_soak_hours": 0}])
        self.assertEqual(r["stages"][0]["min_successful_boots"], 0)
        self.assertIsNone(r["stages"][0]["min_success_rate"])
        self.client.post(f"/admin/v1/rollouts/{r['id']}/start")
        self.assertIn("SOAK_PENDING", self.client.get(f"/admin/v1/rollouts/{r['id']}/promotion-status").json()["reasons"])
        self.assertEqual(self.client.post(f"/admin/v1/rollouts/{r['id']}/promote").status_code, 409)

    def test_selected_rollout_check_interval_survives_preview_refactor(self):
        self.register_all()
        rid = self.rollout(policy={"max_attempts": 1, "check_interval_s": 900})["id"]
        self.client.post(f"/admin/v1/rollouts/{rid}/start")
        a = self.check("retry")
        self.events(flow.dhash("retry"), {"assignment_id": a["assignment_id"], "type": "error",
                    "error_code": 9, "occurred_at": flow.ts()})
        other = self.rollout(name="other", filters={"regions": ["US"]}, policy={"check_interval_s": 3600})["id"]
        self.client.post(f"/admin/v1/rollouts/{other}/start")
        limited = self.check("retry", region="KR")
        self.assertEqual(limited["reason"], "RETRY_LIMIT_REACHED")
        self.assertTrue(810 <= limited["next_check_after_s"] <= 990)
        self.assertNotIn("_rollout_id", limited)

    def test_legacy_history_backfill_is_idempotent(self):
        legacy = Store(":memory:")
        self.addCleanup(legacy.close)
        body = flow.check_body(flow.dhash("legacy"), region="KR")
        with legacy.tx() as conn:
            conn.executescript(SCHEMA)
            for fingerprint, timestamp in ((flow.SRC, flow.ts()), (flow.DST, flow.ts(30))):
                conn.execute("INSERT INTO device_event (device_hash, device, type, fingerprint, occurred_at, received_at, payload) "
                             "VALUES (?, 'pony', 'check', ?, ?, ?, ?)",
                             (body["device_hash"], fingerprint, timestamp, timestamp, json.dumps(body)))
        ota = OtaStore(legacy)
        d = ota.get_device(body["device_hash"])
        self.assertEqual((d["fingerprint"], d["first_seen_at"], d["last_seen_at"]), (flow.DST, flow.ts(), flow.ts(30)))
        ota.set_device_tags(body["device_hash"], ["lab"], "test")
        ota.record_check(body["device_hash"], "pony", flow.SRC, body)
        again = OtaStore(legacy).get_device(body["device_hash"])
        self.assertEqual(again["fingerprint"], flow.SRC)
        self.assertEqual(again["tags"], ["lab"])


if __name__ == "__main__":
    unittest.main()
