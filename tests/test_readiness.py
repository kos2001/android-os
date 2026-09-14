import unittest
from datetime import date

from upgrade_core.readiness import Hal, PlatformProfile, evaluate, load_kb, release_key

AS_OF = date(2026, 9, 14)


def rule_ids(result, severity=None):
    return {f["rule_id"] for f in result["findings"] if severity is None or f["severity"] == severity}


class KnowledgeBaseTests(unittest.TestCase):
    def test_every_supported_kernel_is_known_and_sourced(self):
        kb = load_kb()
        branches = {k["branch"] for k in kb["kernel_branches"]}
        for rel in kb["releases"]:
            with self.subTest(rel["release"]):
                self.assertTrue(set(rel["supported_kernels"]) <= branches)
                self.assertTrue(rel["sources"])
                for kernel in rel.get("kernels_unsupported_from", {}):
                    self.assertIn(kernel, rel["supported_kernels"])

    def test_qpr_kernel_drop_is_consistent(self):
        kb = {r["release"]: r for r in load_kb()["releases"]}
        for kernel, dropped_at in kb["17"]["kernels_unsupported_from"].items():
            self.assertNotIn(kernel, kb[dropped_at]["supported_kernels"])

    def test_release_key(self):
        self.assertLess(release_key("17"), release_key("17-QPR1"))
        self.assertLess(release_key("16-QPR2"), release_key("17"))
        with self.assertRaises(ValueError):
            release_key("seventeen")


class EvaluateTests(unittest.TestCase):
    def test_clean_platform_is_ready(self):
        p = PlatformProfile("clean", "16", "android16-6.12", supports_16kb=True, sepolicy_memfd_ready=True,
                            hals=[Hal("android.hardware.camera.provider", "aidl", "3")])
        result = evaluate(p, "17", AS_OF)
        self.assertTrue(result["ready"])
        self.assertEqual(result["findings"], [])
        self.assertTrue(result["kb_version"].startswith("2026-09-14"))

    def test_legacy_platform_blockers(self):
        p = PlatformProfile("legacy", "14", "android13-5.10", uses_vndk=True, uses_ion=True,
                            support_until=date(2029, 12, 31),
                            hals=[Hal("android.hardware.graphics.composer", "hidl", "2.4")])
        result = evaluate(p, "17", AS_OF)
        self.assertFalse(result["ready"])
        self.assertEqual(rule_ids(result, "blocker"), {"ION_REMOVED", "VNDK_DEPRECATED"})
        self.assertTrue({"KERNEL_COMPAT_QPR", "KERNEL_EOL", "SEPOLICY_MEMFD", "HIDL_HALS"}
                        <= rule_ids(result, "warning"))
        self.assertEqual(result["findings"][0]["severity"], "blocker")

    def test_kernel_dropped_in_qpr_is_blocker(self):
        p = PlatformProfile("p", "17", "android12-5.10", supports_16kb=True, sepolicy_memfd_ready=True)
        self.assertIn("KERNEL_COMPAT", rule_ids(evaluate(p, "17-QPR1", AS_OF), "blocker"))

    def test_eol_passed_is_blocker(self):
        p = PlatformProfile("p", "16", "android13-5.10", supports_16kb=True, sepolicy_memfd_ready=True)
        self.assertIn("KERNEL_EOL", rule_ids(evaluate(p, "17", date(2027, 7, 2)), "blocker"))

    def test_invalid_targets(self):
        p = PlatformProfile("p", "17", "android17-6.18")
        with self.assertRaises(ValueError):
            evaluate(p, "16", AS_OF)
        with self.assertRaises(KeyError):
            evaluate(p, "18", AS_OF)


if __name__ == "__main__":
    unittest.main()
