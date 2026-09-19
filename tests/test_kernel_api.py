import gzip
import unittest

from tests.elf_builder import build_module

try:
    from fastapi.testclient import TestClient

    from backend.app import create_app
    from backend.store import Store
except ImportError:  # 코어만 설치된 환경
    TestClient = None

PLATFORM = {"name": "kbsp", "soc": "soc-k", "android_version": "16", "kernel_branch": "android14-6.1",
            "supports_16kb": True, "sepolicy_memfd_ready": True, "support_until": "2030-06-30"}
CONFIG = b"CONFIG_ARM64=y\nCONFIG_ARM64_4K_PAGES=y\n# CONFIG_ARM64_16K_PAGES is not set\nCONFIG_ION=y\n"
SYMBOLS = b"[abi_symbol_list]\n  printk\n  kmalloc_caches\n"
V14 = "6.1.75-android14-11-g0 SMP preempt mod_unload aarch64"


@unittest.skipIf(TestClient is None, "fastapi not installed (use .venv)")
class KernelApiTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.client = TestClient(create_app(store=self.store, api_keys="", auto_halt_interval_s=0, dev_mode=True))
        self.addCleanup(self.store.close)
        self.pid = self.client.post("/admin/v1/platforms", json=PLATFORM).json()["id"]

    def put_kernel(self, data=None, files=None):
        return self.client.put(f"/admin/v1/platforms/{self.pid}/kernel", data=data or {}, files=files or [])

    def test_kernel_upload_updates_profile_and_merges(self):
        c = self.client
        self.assertEqual(c.get(f"/admin/v1/platforms/{self.pid}/kernel").status_code, 404)
        self.assertEqual(self.put_kernel().status_code, 422)
        r = self.put_kernel({"kernel_release": "6.6.30-android15-8-gabc"})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("android15-6.6", r.text)

        r = self.put_kernel({"kernel_release": "6.1.75-android14-11-g0d5b5cd1f9a4"},
                            [("config", ("config.gz", gzip.compress(CONFIG)))])
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["kmi_generation"], 11)
        self.assertEqual(body["config_hints"]["page_size_kb"], 4)
        platform = body["platform"]
        self.assertEqual((platform["uses_ion"], platform["supports_16kb"]), (True, True))  # 4K config 로 내리지 않음
        self.assertEqual(platform["kernel"]["has_config"], True)

        # modules 만 올려도 release·config 는 유지된다
        ko = build_module("wlan", undefined=("printk", "ion_alloc"), vermagic=V14)
        r = self.put_kernel(files=[("modules", ("wlan.ko", ko)), ("modules", ("core.ko", build_module("core")))])
        self.assertEqual(r.status_code, 200, r.text)
        view = c.get(f"/admin/v1/platforms/{self.pid}/kernel").json()
        self.assertEqual(view["kernel_release"], "6.1.75-android14-11-g0d5b5cd1f9a4")
        self.assertEqual(view["config"]["hints"]["uses_ion"], True)
        self.assertEqual([(m["name"], m["undefined_count"]) for m in view["modules"]], [("wlan", 2), ("core", 0)])

        audit = c.get("/admin/v1/audit", params={"entity": "platform"}).json()
        self.assertEqual(audit[1]["action"], "upload_kernel")
        self.assertIn('"uses_ion": true', audit[1]["after"])

    def test_invalid_artifacts_are_422(self):
        r = self.put_kernel(files=[("modules", ("bad.ko", b"\x7fELF" + b"\0" * 10))])
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "INVALID_KERNEL_ARTIFACT")
        self.assertEqual(self.put_kernel(files=[("config", ("config", b"hello"))]).status_code, 422)
        self.assertEqual(self.put_kernel({"kernel_release": "5.4.0-qgki"}).status_code, 422)
        self.assertIsNone(self.client.get(f"/admin/v1/platforms/{self.pid}").json()["kernel"])

    def test_symbol_lists(self):
        c = self.client
        self.assertEqual(c.put("/admin/v1/kernel/symbol-lists/6.18", files=[("files", ("a", SYMBOLS))]).status_code,
                         422)
        r = c.put("/admin/v1/kernel/symbol-lists/android17-6.18", data={"source": "android17-6.18 tip"},
                  files=[("files", ("abi_gki_aarch64", SYMBOLS)),
                         ("files", ("abi_gki_aarch64_vendor", b"[abi_symbol_list]\n  dma_buf_export\n printk\n"))])
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["symbol_count"], 3)
        bad = c.put("/admin/v1/kernel/symbol-lists/android17-6.18", files=[("files", ("x", b"two words\n"))])
        self.assertEqual(bad.status_code, 422)
        self.assertIn("x: line 1", bad.text)
        empty = c.put("/admin/v1/kernel/symbol-lists/android17-6.18", files=[("files", ("meizu", b"[abi_symbol_list]\n"))])
        self.assertEqual(empty.status_code, 422)
        self.assertEqual(c.get("/admin/v1/kernel/symbol-lists").json()[0]["symbol_count"], 3)

    def test_uprev_endpoint(self):
        r = self.client.get(f"/admin/v1/platforms/{self.pid}/kernel/uprev",
                            params={"target_release": "17", "as_of": "2026-09-14"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["recommended"], "android17-6.18")
        self.assertEqual(body["candidates"][-1]["branch"], "android14-6.1")
        self.assertFalse(body["candidates"][0]["symbol_list_uploaded"])
        self.assertEqual(self.client.get(f"/admin/v1/platforms/{self.pid}/kernel/uprev",
                                         params={"target_release": "99"}).status_code, 422)

    def test_readiness_run_with_kmi_check(self):
        c = self.client
        runs = f"/admin/v1/platforms/{self.pid}/readiness-runs"
        run = c.post(runs, json={"target_release": "17", "as_of": "2026-09-14"}).json()
        self.assertEqual(run["kmi_check"], "skipped: no vendor modules uploaded")
        self.assertIn("KERNEL_EOL", {f["rule_id"] for f in run["findings"]})

        ko = build_module("wlan", undefined=("printk", "ion_alloc"), vermagic=V14)
        self.put_kernel(files=[("modules", ("wlan.ko", ko))])
        plan = {"target_release": "17", "as_of": "2026-09-14", "target_kernel_branch": "android17-6.18"}
        self.assertEqual(c.post(runs, json=plan).json()["kmi_check"],
                         "skipped: no KMI symbol list uploaded for android17-6.18")

        c.put("/admin/v1/kernel/symbol-lists/android17-6.18", files=[("files", ("abi_gki_aarch64", SYMBOLS))])
        run = c.post(runs, json=plan).json()
        self.assertEqual(run["kmi_check"], "included: 1 modules vs android17-6.18 (2 symbols)")
        self.assertEqual(run["kernel_branch"], "android17-6.18")
        by_rule = {f["rule_id"]: f for f in run["findings"]}
        self.assertNotIn("KERNEL_EOL", by_rule)
        self.assertIn("ion_alloc", by_rule["KMI_SYMBOL_MISSING"]["title"])
        self.assertIsNotNone(by_rule["KMI_SYMBOL_MISSING"]["work_item_id"])
        self.assertIn("KERNEL_MODULE_REBUILD", by_rule)

        older = {**plan, "target_kernel_branch": "android13-5.15"}
        self.assertEqual(c.post(runs, json=older).status_code, 422)


if __name__ == "__main__":
    unittest.main()
