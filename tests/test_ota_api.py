import hashlib
import io
import unittest
from datetime import datetime, timedelta, timezone

from tests.test_ota_package import DST, SRC, build_zip
from upgrade_core.rollout import in_rollout

try:
    from fastapi.testclient import TestClient

    from backend.app import create_app
    from backend.store import Store
except ImportError:
    TestClient = None

OLD = "vendor/pony/pony:15/AP4A/0:user/release-keys"
B1 = "6f1c2e4a-9b3d-4c5e-8f7a-1b2c3d4e5f60"  # /proc/sys/kernel/random/boot_id 형식
B2 = "0a9b8c7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d"
BASE = "https://ota.example.com/pony/"


def dhash(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def check_body(device_hash, fingerprint=SRC, **kw):
    body = {"device": "pony", "fingerprint": fingerprint, "build_timestamp": 1_750_000_000,
            "security_patch": "2026-06-05", "channel": "stable", "device_hash": device_hash}
    body.update(kw)
    return body


def ts(minutes=0):
    return (datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)).isoformat()


@unittest.skipIf(TestClient is None, "fastapi not installed (use .venv)")
class OtaFlowTests(unittest.TestCase):
    def setUp(self):
        self.packages = {
            BASE + "full.zip": build_zip(pre_build=None)[0].getvalue(),
            BASE + "delta.zip": build_zip(pre_build=SRC)[0].getvalue(),
            BASE + "downgrade.zip": build_zip(pre_build=None, downgrade=True)[0].getvalue(),
        }
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        opener = lambda url: io.BytesIO(self.packages[url])  # noqa: E731
        self.client = TestClient(create_app(store=self.store, api_keys="", device_keys="",
                                            package_opener=opener, auto_halt_interval_s=0, dev_mode=True))

    def register_all(self):
        c = self.client
        full = c.post("/admin/v1/packages", json={"url": BASE + "full.zip"})
        self.assertEqual(full.status_code, 201, full.text)
        delta = c.post("/admin/v1/packages", json={"url": BASE + "delta.zip", "sha256": "a" * 64}).json()
        return full.json(), delta

    def rollout(self, **kw):
        body = {"name": "pony-17", "target_fingerprint": DST, "channel": "stable",
                "stages": [{"percent": 100, "min_soak_hours": 0}],
                "halt_rules": {"min_sample": 1, "max_error_rate": 0.4}}
        body.update(kw)
        r = self.client.post("/admin/v1/rollouts", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def events(self, device_hash, *events):
        r = self.client.post("/device/v1/events", json={"device_hash": device_hash, "events": list(events)})
        self.assertEqual(r.status_code, 202, r.text)
        return r.json()

    def test_package_registration(self):
        c = self.client
        full, delta = self.register_all()
        self.assertEqual((full["status"], full["type"], full["post_build"]), ("ready", "full", DST))
        self.assertEqual((delta["type"], delta["pre_builds"], delta["sha256"]), ("incremental", [SRC], "a" * 64))
        self.assertEqual(c.post("/admin/v1/packages", json={"url": BASE + "full.zip"}).status_code, 409)
        rejected = c.post("/admin/v1/packages", json={"url": BASE + "downgrade.zip"}).json()
        self.assertEqual(rejected["status"], "rejected")
        self.assertTrue(any("ota-downgrade" in r for r in rejected["reject_reasons"]))
        self.assertEqual(len(c.get("/admin/v1/packages?device=pony").json()), 3)
        self.assertEqual(c.post(f"/admin/v1/packages/{full['id']}/retire").json()["status"], "retired")
        with self.assertRaises(Exception):  # 트리거: payload 필드 불변
            with self.store.tx() as conn:
                conn.execute("UPDATE ota_package SET payload_offset = 1 WHERE id = ?", (delta["id"],))

    def test_rollout_requires_ready_package_and_ordered_stages(self):
        c = self.client
        body = {"name": "x", "target_fingerprint": DST, "channel": "stable", "stages": [{"percent": 5}]}
        self.assertEqual(c.post("/admin/v1/rollouts", json=body).status_code, 404)  # 빌드 미등록
        self.register_all()
        bad = {**body, "stages": [{"percent": 50}, {"percent": 10}]}
        self.assertEqual(c.post("/admin/v1/rollouts", json=bad).status_code, 409)

    def test_update_check_install_and_boot_outcomes(self):
        c = self.client
        full, delta = self.register_all()
        # 롤아웃 전: 업데이트 없음
        self.assertEqual(c.post("/device/v1/update-check", json=check_body(dhash("a"))).json()["reason"], "UP_TO_DATE")
        rid = self.rollout()["id"]
        self.assertEqual(c.post("/device/v1/update-check", json=check_body(dhash("a"))).json()["reason"], "UP_TO_DATE")
        c.post(f"/admin/v1/rollouts/{rid}/start")

        a = c.post("/device/v1/update-check", json=check_body(dhash("a"))).json()
        self.assertTrue(a["update_available"])
        self.assertEqual(a["package"]["id"], delta["id"])
        self.assertEqual(a["package"]["headers"][1], "FILE_SIZE=2052")
        b = c.post("/device/v1/update-check", json=check_body(dhash("b"), fingerprint=OLD)).json()
        self.assertEqual(b["package"]["id"], full["id"])
        self.assertGreater(b["next_check_after_s"], 0)

        # a: 설치 성공
        self.events(dhash("a"), {"assignment_id": a["assignment_id"], "type": "download_started", "occurred_at": ts()},
                    {"assignment_id": a["assignment_id"], "type": "updated_need_reboot", "occurred_at": ts(30)})
        dup = self.events(dhash("a"), {"assignment_id": a["assignment_id"], "type": "download_started",
                                       "occurred_at": ts()})
        self.assertEqual(dup, {"accepted": 0, "duplicates": 1})
        after = c.post("/device/v1/update-check",
                       json=check_body(dhash("a"), fingerprint=DST, build_timestamp=1_783_000_000)).json()
        self.assertEqual(after["reason"], "UP_TO_DATE")

        # b: 새 슬롯 부팅 실패 → 이전 fingerprint 로 체크인 → fallback, 재제공
        self.events(dhash("b"), {"assignment_id": b["assignment_id"], "type": "updated_need_reboot",
                                 "boot_id": B1, "occurred_at": ts()})
        # 재부팅 전 체크인(같은 boot_id): 폴백으로 오판하지 않고 재설치도 하지 않음
        before_reboot = c.post("/device/v1/update-check",
                               json=check_body(dhash("b"), fingerprint=OLD, boot_id=B1)).json()
        self.assertEqual((before_reboot["update_available"], before_reboot["reason"], before_reboot["attempt"]),
                         (False, "PENDING_REBOOT", 1))
        self.assertEqual(c.get(f"/admin/v1/rollouts/{rid}").json()["assignments"],
                         {"boot_success": 1, "installed_pending_reboot": 1})
        retry = c.post("/device/v1/update-check", json=check_body(dhash("b"), fingerprint=OLD,
                                                                   boot_id=B2)).json()
        self.assertEqual(retry["attempt"], 2)
        self.assertTrue(retry["update_available"])
        counts = c.get(f"/admin/v1/rollouts/{rid}").json()["assignments"]
        self.assertEqual(counts, {"boot_success": 1, "offered": 1})

        # 다른 기기의 assignment 로 이벤트 보고 불가
        r = c.post("/device/v1/events", json={"device_hash": dhash("z"), "events": [
            {"assignment_id": a["assignment_id"], "type": "download_started", "occurred_at": ts()}]})
        self.assertEqual(r.status_code, 404)
        r = c.post("/device/v1/events", json={"device_hash": dhash("a"), "events": [
            {"assignment_id": a["assignment_id"], "type": "error", "occurred_at": ts(99)}]})
        self.assertEqual(r.status_code, 422)

    def test_errors_metrics_and_auto_halt(self):
        c = self.client
        self.register_all()
        rid = self.rollout(halt_mode="stop_new")["id"]
        c.post(f"/admin/v1/rollouts/{rid}/start")
        first = c.post("/device/v1/update-check", json=check_body(dhash("d1"))).json()
        second = c.post("/device/v1/update-check", json=check_body(dhash("d2"))).json()
        self.events(dhash("d1"), {"assignment_id": first["assignment_id"], "type": "download_started",
                                  "occurred_at": ts()},
                    {"assignment_id": first["assignment_id"], "type": "error", "error_code": (1 << 30) | 9,
                     "occurred_at": ts(5)})
        metrics = c.get(f"/admin/v1/rollouts/{rid}/metrics").json()
        self.assertEqual(metrics["errors"], [{"code": 9, "name": "DownloadTransferError", "devices": 1}])

        dry = c.post(f"/admin/v1/rollouts/{rid}/evaluate-halt").json()
        self.assertTrue(dry["halt"])
        self.assertEqual(dry["state"], "active")
        applied = c.post(f"/admin/v1/rollouts/{rid}/evaluate-halt?apply=true").json()
        self.assertEqual((applied["state"], applied["halted_now"]), ("halted", True))
        self.assertIn("error rate", c.get(f"/admin/v1/rollouts/{rid}").json()["halt_reason"])

        # stop_new: 이미 할당된 기기는 계속, 신규 기기는 차단
        self.assertTrue(c.post("/device/v1/update-check", json=check_body(dhash("d2"))).json()["update_available"])
        self.assertEqual(c.post("/device/v1/update-check", json=check_body(dhash("new"))).json()["reason"],
                         "ROLLOUT_HALTED")
        self.assertEqual(second["assignment_id"],
                         c.post("/device/v1/update-check", json=check_body(dhash("d2"))).json()["assignment_id"])
        self.assertEqual(c.post(f"/admin/v1/rollouts/{rid}/resume").status_code, 409)
        self.assertEqual(c.post(f"/admin/v1/rollouts/{rid}/halt", json={"reason": "x"}).status_code, 409)

    def test_stages_soak_and_bucketing(self):
        c = self.client
        self.register_all()
        rid = self.rollout(stages=[{"percent": 10, "min_soak_hours": 24}, {"percent": 50, "min_soak_hours": 24}])["id"]
        self.assertEqual(c.post(f"/admin/v1/rollouts/{rid}/halt").status_code, 409)  # draft 에서는 불가
        started = c.post(f"/admin/v1/rollouts/{rid}/start").json()
        self.assertEqual((started["current_stage"], started["current_percent"]), (1, 10))
        outside = next(h for h in (dhash(f"dev{i}") for i in range(500)) if not in_rollout(rid, h, 50))
        inside_second = next(h for h in (dhash(f"dev{i}") for i in range(500))
                             if in_rollout(rid, h, 50) and not in_rollout(rid, h, 10))
        self.assertEqual(c.post("/device/v1/update-check", json=check_body(inside_second)).json()["reason"],
                         "NOT_IN_ROLLOUT")
        r = c.post(f"/admin/v1/rollouts/{rid}/promote")
        self.assertEqual(r.status_code, 409)
        self.assertIn("soak", r.json()["error"]["message"])
        with self.store.tx() as conn:
            conn.execute("UPDATE rollout_stage SET promoted_at = '2020-01-01T00:00:00+00:00' WHERE rollout_id = ?",
                         (rid,))
        self.assertEqual(c.post(f"/admin/v1/rollouts/{rid}/promote").json()["current_percent"], 50)
        self.assertTrue(c.post("/device/v1/update-check", json=check_body(inside_second)).json()["update_available"])
        self.assertEqual(c.post("/device/v1/update-check", json=check_body(outside)).json()["reason"], "NOT_IN_ROLLOUT")
        with self.store.tx() as conn:
            conn.execute("UPDATE rollout_stage SET promoted_at = '2020-01-01T00:00:00+00:00' WHERE rollout_id = ?",
                         (rid,))
        self.assertEqual(c.post(f"/admin/v1/rollouts/{rid}/promote").status_code, 409)  # 마지막 단계
        self.assertEqual(c.post(f"/admin/v1/rollouts/{rid}/complete").json()["state"], "completed")
        actions = [a["action"] for a in c.get("/admin/v1/audit?entity=rollout").json()]
        self.assertEqual(actions, ["complete", "promote", "start", "create"])

    def test_delta_candidates_report(self):
        c = self.client
        self.register_all()
        for i in range(3):
            c.post("/device/v1/update-check", json=check_body(dhash(f"s{i}")))
        c.post("/device/v1/update-check", json=check_body(dhash("o1"), fingerprint=OLD))
        c.post("/device/v1/update-check", json=check_body(dhash("s0")))  # 같은 기기 재체크는 1대로 센다
        report = c.get("/admin/v1/reports/delta-candidates", params={"target_fingerprint": DST}).json()
        self.assertEqual(report["active_devices_not_on_target"], 4)
        self.assertEqual([(s["fingerprint"], s["devices"], s["has_incremental"]) for s in report["sources"]],
                         [(SRC, 3, True), (OLD, 1, False)])

    def test_background_auto_halt_loop(self):
        import time
        store = Store(":memory:")
        self.addCleanup(store.close)
        opener = lambda url: io.BytesIO(self.packages[url])  # noqa: E731
        app = create_app(store=store, api_keys="", device_keys="", package_opener=opener, auto_halt_interval_s=0.05,
                         dev_mode=True)
        with TestClient(app) as c:  # lifespan 에서 루프 시작
            c.post("/admin/v1/packages", json={"url": BASE + "full.zip"})
            rid = c.post("/admin/v1/rollouts", json={"name": "bg", "target_fingerprint": DST, "channel": "stable",
                                                     "stages": [{"percent": 100}],
                                                     "halt_rules": {"min_sample": 1, "max_error_rate": 0.1}}).json()["id"]
            c.post(f"/admin/v1/rollouts/{rid}/start")
            aid = c.post("/device/v1/update-check", json=check_body(dhash("bg"))).json()["assignment_id"]
            c.post("/device/v1/events", json={"device_hash": dhash("bg"), "events": [
                {"assignment_id": aid, "type": "error", "error_code": 60, "occurred_at": ts()}]})
            deadline = time.monotonic() + 3
            while c.get(f"/admin/v1/rollouts/{rid}").json()["state"] != "halted" and time.monotonic() < deadline:
                time.sleep(0.05)
            rollout = c.get(f"/admin/v1/rollouts/{rid}").json()
        self.assertEqual(rollout["state"], "halted")
        self.assertEqual(store.audit("rollout")[0]["actor"], "auto-halt")

    def test_control_headers_follow_update_engine_bool_format(self):
        from backend.ota_api import apply_payload_headers
        pkg = {"payload_properties": {"FILE_HASH": "h", "FILE_SIZE": "1", "METADATA_HASH": "m", "METADATA_SIZE": "2"},
               "wipe": False, "spl_downgrade": False}
        self.assertEqual(apply_payload_headers(pkg, {}), ["FILE_HASH=h", "FILE_SIZE=1", "METADATA_HASH=m",
                                                          "METADATA_SIZE=2"])
        extra = apply_payload_headers({**pkg, "wipe": True}, {"switch_slot_on_reboot": False})[4:]
        self.assertEqual(extra, ["POWERWASH=1", "SWITCH_SLOT_ON_REBOOT=0"])

    def test_device_auth_and_validation(self):
        store = Store(":memory:")
        self.addCleanup(store.close)
        client = TestClient(create_app(store=store, api_keys="", device_keys="fleet-key", auto_halt_interval_s=0,
                                       dev_mode=True))
        self.assertEqual(client.post("/device/v1/update-check", json=check_body(dhash("a"))).status_code, 401)
        ok = client.post("/device/v1/update-check", json=check_body(dhash("a")),
                         headers={"Authorization": "Bearer fleet-key"})
        self.assertEqual(ok.status_code, 200)
        bad = client.post("/device/v1/update-check", json=check_body("not-a-hash"),
                          headers={"Authorization": "Bearer fleet-key"})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(client.post("/admin/v1/packages", json={"url": "http://x/y.zip"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(TestClient is None, "fastapi not installed (use .venv)")
class DashboardApiTests(OtaFlowTests.__base__):
    def test_overview_and_timeseries(self):
        flow = OtaFlowTests("test_package_registration")
        flow.setUp()
        self.addCleanup(flow.doCleanups)
        c = flow.client
        flow.register_all()
        rid = flow.rollout()["id"]
        c.post(f"/admin/v1/rollouts/{rid}/start")
        a = c.post("/device/v1/update-check", json=check_body(dhash("a"))).json()
        flow.events(dhash("a"), {"assignment_id": a["assignment_id"], "type": "download_started", "occurred_at": ts()},
                    {"assignment_id": a["assignment_id"], "type": "updated_need_reboot", "occurred_at": ts(1)})
        c.post("/device/v1/update-check", json=check_body(dhash("a"), fingerprint=DST, build_timestamp=1_783_000_000))
        series = c.get(f"/admin/v1/rollouts/{rid}/timeseries?hours=6").json()
        self.assertEqual(len(series), 6)
        self.assertEqual({k: series[-1][k] for k in ("download_started", "updated_need_reboot", "boot_success")},
                         {"download_started": 1, "updated_need_reboot": 1, "boot_success": 1})
        ov = c.get("/admin/v1/overview").json()
        self.assertEqual((ov["devices_checked_in_24h"], ov["boot_success_24h"], ov["rollouts"]),
                         (1, 1, {"active": 1}))
        self.assertEqual(ov["packages"], {"ready": 2})
        self.assertEqual(c.get(f"/admin/v1/rollouts/{rid}/timeseries?hours=0").status_code, 422)
