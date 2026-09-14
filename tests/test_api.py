import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient

    from backend.app import create_app
    from backend.store import Store
except ImportError:  # 코어만 설치된 환경
    TestClient = None

FIX = Path(__file__).parent / "fixtures" / "vintf"
BASE8 = b'<manifest version="1.0" type="device" target-level="8"/>'
HIDL_MAPPER = (b'<manifest version="1.0" type="device"><hal format="hidl">'
               b'<name>android.hardware.graphics.mapper</name><transport>passthrough</transport>'
               b'<fqname>@4.0::IMapper/default</fqname></hal></manifest>')
PLATFORM = {"name": "pony-bsp", "soc": "exynos-x", "android_version": "15", "kernel_branch": "android13-5.10",
            "uses_ion": True, "support_until": "2029-12-31"}


@unittest.skipIf(TestClient is None, "fastapi not installed (use .venv)")
class ReadinessApiTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.client = TestClient(create_app(store=self.store, api_keys="", auto_halt_interval_s=0, dev_mode=True))
        self.addCleanup(self.store.close)

    def upload_matrix(self, release, name):
        with open(FIX / name, "rb") as f:
            return self.client.post("/admin/v1/matrices", data={"release": release, "source": f"fixture:{name}"},
                                    files={"file": (name, f, "application/xml")})

    def test_end_to_end_readiness_flow(self):
        c = self.client
        pid = c.post("/admin/v1/platforms", json=PLATFORM).json()["id"]
        self.assertEqual(c.post("/admin/v1/platforms", json=PLATFORM).status_code, 409)

        r = c.put(f"/admin/v1/platforms/{pid}/manifest",
                  files=[("files", ("manifest.xml", BASE8)), ("files", ("mapper.xml", HIDL_MAPPER)),
                         ("files", ("health.xml", (FIX / "frag.health.xml").read_bytes()))])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["platform"]["fcm_target_level"], "8")
        self.assertEqual(r.json()["hal_instances_by_format"], {"hidl": 1, "aidl": 1})

        run = c.post(f"/admin/v1/platforms/{pid}/readiness-runs",
                     json={"target_release": "17", "as_of": "2026-09-14"}).json()
        self.assertTrue(run["hal_check"].startswith("skipped"))
        self.assertEqual(self.upload_matrix("17", "a17.8.xml").json()["level"], "8")
        run = c.post(f"/admin/v1/platforms/{pid}/readiness-runs",
                     json={"target_release": "17-QPR1", "as_of": "2026-09-14"}).json()
        self.assertEqual(run["hal_check"], "included: matrix level 8")  # 17 매트릭스로 폴백
        self.assertFalse(run["ready"])
        rules = {f["rule_id"]: f for f in run["findings"]}
        self.assertEqual(rules["KERNEL_COMPAT"]["severity"], "blocker")
        self.assertEqual(rules["ION_REMOVED"]["severity"], "blocker")
        self.assertNotIn("HAL_NOT_IN_MATRIX", rules)  # level 8 에는 HIDL mapper 4.0 이 있다
        self.assertIsNone(rules["PAGE_16KB"]["work_item_id"])  # info 는 작업 항목을 만들지 않는다

        item = rules["ION_REMOVED"]["work_item_id"]
        self.assertEqual(c.patch(f"/admin/v1/work-items/{item}", json={"status": "waived"}).status_code, 409)
        r = c.patch(f"/admin/v1/work-items/{item}", json={"status": "waived", "waive_reason": "DMA-BUF 이전 완료 확인"})
        self.assertEqual(r.json()["status"], "waived")
        fetched = c.get(f"/admin/v1/readiness-runs/{run['id']}").json()
        self.assertEqual(next(f for f in fetched["findings"] if f["rule_id"] == "ION_REMOVED")["status"], "waived")
        self.assertEqual(len(c.get(f"/admin/v1/platforms/{pid}/readiness-runs").json()), 2)
        actions = {a["action"] for a in c.get("/admin/v1/audit").json()}
        self.assertTrue({"create", "upload_manifest", "upload_matrix", "update"} <= actions)

    def test_matrix_diff_endpoint_on_real_matrices(self):
        r = self.client.post("/admin/v1/vintf/matrix-diff",
                             files={"old": ("a", (FIX / "a16.202504.xml").read_bytes()),
                                    "new": ("b", (FIX / "a17.202604.xml").read_bytes())})
        self.assertEqual(r.json()["removed"], ["android.hardware.health.storage (aidl)"])

    def test_validation_errors(self):
        c = self.client
        self.assertEqual(c.post("/admin/v1/platforms", json={**PLATFORM, "kernel_branch": "5.10"}).status_code, 422)
        self.assertEqual(c.post("/admin/v1/platforms", json={**PLATFORM, "android_version": "x"}).status_code, 422)
        pid = c.post("/admin/v1/platforms", json=PLATFORM).json()["id"]
        self.assertEqual(c.post(f"/admin/v1/platforms/{pid}/readiness-runs", json={"target_release": "14"}).status_code,
                         422)
        bad = c.put(f"/admin/v1/platforms/{pid}/manifest", files=[("files", ("m.xml", b"<oops"))])
        self.assertEqual(bad.json()["error"]["code"], "INVALID_VINTF")
        self.assertEqual(c.get("/admin/v1/platforms/999").status_code, 404)
        self.assertEqual(c.post("/admin/v1/packages/inspect", json={"url": "http://x/y.zip"}).status_code, 422)


@unittest.skipIf(TestClient is None, "fastapi not installed (use .venv)")
class AuthTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.client = TestClient(create_app(store=self.store, api_keys="k-eng:alice:engineer,k-view:bob:viewer",
                                            package_hosts="dl.google.com", device_keys="fleet",
                                            auto_halt_interval_s=0, dev_mode=False))

    def test_roles(self):
        c = self.client
        self.assertEqual(c.get("/admin/v1/platforms").status_code, 401)
        view = {"Authorization": "Bearer k-view"}
        self.assertEqual(c.get("/admin/v1/platforms", headers=view).status_code, 200)
        self.assertEqual(c.post("/admin/v1/platforms", json=PLATFORM, headers=view).status_code, 403)
        r = c.post("/admin/v1/platforms", json=PLATFORM, headers={"Authorization": "Bearer k-eng"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.store.audit("platform")[0]["actor"], "alice")
        self.assertEqual(c.get("/api/health").status_code, 200)

    def test_package_host_allowlist(self):
        from backend.app import parse_api_keys
        app = create_app(store=self.store, api_keys="k:ci:pipeline", package_hosts="dl.google.com",
                         device_keys="fleet", auto_halt_interval_s=0, dev_mode=False)
        r = TestClient(app).post("/admin/v1/packages/inspect", json={"url": "https://evil.example/ota.zip"},
                                 headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 403)
        with self.assertRaises(ValueError):
            parse_api_keys("k:x:superuser")
        with self.assertRaises(ValueError):  # 빈 키는 무인증 요청과 일치하므로 거부
            parse_api_keys(":ci:admin")

    def test_fails_closed_without_configuration(self):
        with self.assertRaisesRegex(RuntimeError, "ANDROID_OS_API_KEYS.*ANDROID_OS_DEVICE_KEYS.*PACKAGE_HOSTS"):
            create_app(store=self.store, api_keys="", device_keys="", package_hosts="", dev_mode=False)
        app = create_app(store=self.store, api_keys="k:ci:pipeline", device_keys="fleet", package_hosts="h",
                         auto_halt_interval_s=0, dev_mode=False)
        c = TestClient(app)
        self.assertEqual(c.get("/admin/v1/platforms").status_code, 401)
        self.assertEqual(c.get("/admin/v1/platforms", headers={"Authorization": "Bearer "}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
