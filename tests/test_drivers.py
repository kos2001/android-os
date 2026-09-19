import unittest

from tests.elf_builder import build_module
from upgrade_core.drivers import build_inventory, classify_hal, classify_module, module_buses, module_uses_ion
from upgrade_core.kernel import inspect_module
from upgrade_core.vintf import parse_manifest

try:
    from fastapi.testclient import TestClient

    from backend.app import create_app
    from backend.store import Store
except ImportError:  # 코어만 설치된 환경
    TestClient = None

V14 = "6.1.75-android14-11-g0 SMP preempt mod_unload aarch64"
MANIFEST = b"""<manifest version="1.0" type="device" target-level="8">
  <hal format="aidl"><name>android.hardware.camera.provider</name><version>2</version>
    <fqname>ICameraProvider/internal/0</fqname><fqname>ICameraProvider/external/0</fqname></hal>
  <hal format="hidl"><name>android.hardware.audio</name><transport>hwbinder</transport>
    <fqname>@7.1::IDevicesFactory/default</fqname></hal>
  <hal format="aidl"><name>vendor.acme.fancy</name><fqname>IFancy/default</fqname></hal>
</manifest>"""


def ko(name, undefined=(), **kw):
    return inspect_module(build_module(name, undefined=undefined, vermagic=V14, **kw), f"{name}.ko")


class ClassificationTests(unittest.TestCase):
    def test_module_subsystem_from_imported_apis(self):
        cases = {
            "display": ("drm_dev_register", "drm_crtc_init_with_planes", "dma_buf_get"),
            "camera": ("v4l2_device_register", "vb2_queue_init", "_printk"),
            "audio": ("snd_soc_register_component", "snd_pcm_period_elapsed"),
            "wifi": ("cfg80211_scan_done", "wiphy_register"),
            "power": ("regulator_enable", "thermal_zone_device_update"),
            "memory": ("dma_heap_add", "dma_buf_export"),
            "other": ("_printk", "kmalloc_caches"),
        }
        for expected, syms in cases.items():
            with self.subTest(expected):
                self.assertEqual(classify_module(ko("m", syms)), expected)

    def test_buses_description_and_ion(self):
        m = ko("touch", ("input_register_device", "ion_alloc"), description="Acme touch panel",
               aliases=("of:N*T*Cacme,touch", "i2c:acme-touch", "i2c:acme-touch2", "weird:x"))
        self.assertEqual(m.description, "Acme touch panel")
        self.assertEqual(module_buses(m), ["i2c", "of"])
        self.assertTrue(module_uses_ion(m))
        self.assertFalse(module_uses_ion(ko("clean", ("dma_heap_add",))))

    def test_hal_subsystem(self):
        self.assertEqual(classify_hal("android.hardware.graphics.composer3"), "display")
        self.assertEqual(classify_hal("android.hardware.health"), "power")
        self.assertEqual(classify_hal("vendor.acme.fancy"), "other")
        self.assertEqual(classify_hal("android.hardware.unknownthing"), "other")

    def test_inventory_groups_and_totals(self):
        mods = [ko("cam", ("v4l2_device_register",), aliases=("of:N*T*Cacme,cam",)),
                ko("aud", ("snd_soc_register_component", "ion_alloc"))]
        inv = build_inventory(mods, parse_manifest(MANIFEST.decode()).hals)
        groups = {g["subsystem"]: g for g in inv["subsystems"]}
        self.assertEqual(list(groups), ["camera", "audio", "other"])  # SUBSYSTEMS 순서, 빈 그룹 제외
        self.assertEqual([k["name"] for k in groups["camera"]["kernel"]], ["cam"])
        self.assertEqual(len(groups["camera"]["hal"]), 1)  # 같은 HAL 의 인스턴스 2개 → 한 줄
        self.assertEqual(groups["audio"]["hal"][0]["format"], "hidl")
        self.assertEqual(groups["camera"]["kernel"][0]["branch"], "android14-6.1")
        self.assertEqual(inv["totals"], {"kernel": 2, "hal": 3, "hidl": 1, "ion_drivers": ["aud"]})

    def test_old_stored_modules_without_new_fields(self):
        from upgrade_core.kernel import KernelModule
        m = KernelModule.from_dict({"filename": "a.ko", "name": "a", "vermagic": None, "license": None,
                                    "depends": [], "undefined": ["drm_x"], "exports": []})
        self.assertEqual((m.description, m.aliases), (None, ()))
        self.assertEqual(classify_module(m), "display")


@unittest.skipIf(TestClient is None, "fastapi not installed (use .venv)")
class DriversApiTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.client = TestClient(create_app(store=self.store, api_keys="", auto_halt_interval_s=0, dev_mode=True))
        self.addCleanup(self.store.close)
        self.pid = self.client.post("/admin/v1/platforms", json={
            "name": "drv", "soc": "s", "android_version": "16", "kernel_branch": "android14-6.1"}).json()["id"]

    def test_inventory_endpoint(self):
        c, url = self.client, f"/admin/v1/platforms/{self.pid}/drivers"
        empty = c.get(url).json()
        self.assertEqual((empty["subsystems"], empty["has_modules"], empty["kmi_checked"]), ([], False, False))

        c.put(f"/admin/v1/platforms/{self.pid}/manifest", files=[("files", ("manifest.xml", MANIFEST))])
        c.put(f"/admin/v1/platforms/{self.pid}/kernel", files=[
            ("modules", ("cam.ko", build_module("cam", undefined=("v4l2_device_register", "ion_alloc"),
                                                vermagic=V14, description="Acme camera"))),
        ])
        body = c.get(url).json()
        self.assertTrue(body["has_manifest"] and body["has_modules"])
        cam = next(g for g in body["subsystems"] if g["subsystem"] == "camera")
        self.assertEqual(cam["kernel"][0]["detail"], "Acme camera")
        self.assertIsNone(cam["kernel"][0]["kmi_missing"])
        self.assertEqual(body["totals"]["ion_drivers"], ["cam"])

        c.put("/admin/v1/kernel/symbol-lists/android17-6.18",
              files=[("files", ("base", b"[abi_symbol_list]\n  v4l2_device_register\n"))])
        planned = c.get(url, params={"kernel_branch": "android17-6.18"}).json()
        self.assertTrue(planned["kmi_checked"])
        cam = next(g for g in planned["subsystems"] if g["subsystem"] == "camera")
        self.assertEqual((cam["kernel"][0]["kmi_missing"], cam["kernel"][0]["kmi_missing_symbols"]), (1, ["ion_alloc"]))
        self.assertEqual(c.get(url, params={"kernel_branch": "6.18"}).status_code, 422)

        run = c.post(f"/admin/v1/platforms/{self.pid}/readiness-runs", json={"target_release": "17"}).json()
        ion = next(f for f in run["findings"] if f["rule_id"] == "ION_REMOVED")
        self.assertIn("cam", ion["detail"])
        self.assertIn("Drivers using ION APIs: cam", ion["detail_en"])


if __name__ == "__main__":
    unittest.main()
