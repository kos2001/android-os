import gzip
import unittest
from datetime import date

from tests.elf_builder import build_module
from upgrade_core.kernel import (KernelArtifactError, branch_key, check_modules, config_hints, inspect_module,
                                 parse_kconfig, parse_kernel_release, parse_symbol_list, read_config_bytes,
                                 recommended_uprev, uprev_candidates)
from upgrade_core.readiness import PlatformProfile, evaluate, load_kb, release_entry

AS_OF = date(2026, 9, 14)
CONFIG = """#
# Automatically generated file; DO NOT EDIT.
# Linux/arm64 6.1.75 Kernel Configuration
#
CONFIG_ARM64=y
CONFIG_ARM64_4K_PAGES=y
# CONFIG_ARM64_16K_PAGES is not set
CONFIG_ION=y
CONFIG_DMABUF_HEAPS=y
CONFIG_MODVERSIONS=y
CONFIG_LOCALVERSION="-android14-11"
CONFIG_NR_CPUS=32
"""
SYMBOL_LIST = """[abi_symbol_list]
# commonly used symbols
  kmalloc_caches
  printk
  __traceiter_android_vh_foo

[abi_symbol_list]
  dma_buf_export
"""


def rule_ids(result, severity=None):
    return [f["rule_id"] for f in result["findings"] if severity is None or f["severity"] == severity]


class ReleaseStringTests(unittest.TestCase):
    def test_gki_release_string(self):
        r = parse_kernel_release("6.1.75-android14-11-g0d5b5cd1f9a4-ab11621366\n")
        self.assertEqual(r.version, (6, 1, 75))
        self.assertEqual(r.branch, "android14-6.1")
        self.assertEqual(r.kmi_generation, 11)
        self.assertEqual(r.suffix, "g0d5b5cd1f9a4-ab11621366")
        self.assertEqual(parse_kernel_release("6.18.0-android17-0").suffix, None)

    def test_non_gki_release_rejected(self):
        for bad in ("5.4.210-qgki", "6.1.75", "android14-6.1", ""):
            with self.subTest(bad), self.assertRaises(KernelArtifactError):
                parse_kernel_release(bad)

    def test_branch_order(self):
        self.assertLess(branch_key("android13-5.15"), branch_key("android14-5.15"))
        self.assertLess(branch_key("android14-5.15"), branch_key("android14-6.1"))
        with self.assertRaises(KernelArtifactError):
            branch_key("6.1")


class ConfigTests(unittest.TestCase):
    def test_parse_and_hints(self):
        options = parse_kconfig(CONFIG)
        self.assertEqual(options["CONFIG_ARM64_16K_PAGES"], "n")
        self.assertEqual(options["CONFIG_LOCALVERSION"], '"-android14-11"')
        self.assertEqual(config_hints(options), {"uses_ion": True, "supports_16kb": False, "page_size_kb": 4,
                                                 "dmabuf_heaps": True, "modversions": True})
        hints = config_hints(parse_kconfig("CONFIG_ARM64_16K_PAGES=y\n# CONFIG_ION is not set\n"))
        self.assertEqual((hints["supports_16kb"], hints["uses_ion"], hints["page_size_kb"]), (True, False, 16))

    def test_gzip_config(self):
        self.assertEqual(read_config_bytes(gzip.compress(CONFIG.encode())), CONFIG)
        with self.assertRaises(KernelArtifactError):
            read_config_bytes(b"\x1f\x8b" + b"garbage")
        with self.assertRaises(KernelArtifactError):
            parse_kconfig("not a config\n")


class ModuleTests(unittest.TestCase):
    def test_inspect_module(self):
        ko = build_module("wlan", undefined=("printk", "kmalloc_caches", "vendor_helper"),
                          exports=("wlan_register",), locals_=("wlan_probe",), depends="vendor_core,cfg80211")
        m = inspect_module(ko, "vendor/lib/modules/wlan.ko")
        self.assertEqual(m.name, "wlan")
        self.assertEqual(m.undefined, ("kmalloc_caches", "printk", "vendor_helper"))
        self.assertEqual(m.exports, ("wlan_register",))
        self.assertEqual(m.depends, ("vendor_core", "cfg80211"))
        self.assertEqual(m.license, "GPL")
        self.assertEqual(m.kernel_release, "6.18.0-android17-0-g0")

    def test_name_falls_back_to_filename(self):
        self.assertEqual(inspect_module(build_module(name=None), "dir/touch.ko").name, "touch")

    def test_rejects_non_modules(self):
        ko = build_module()
        cases = {"not elf": b"MZ" + ko[2:], "elf32": ko[:4] + b"\x01" + ko[5:], "big endian": ko[:5] + b"\x02" + ko[6:],
                 "ET_EXEC": ko[:16] + b"\x02\x00" + ko[18:], "truncated": ko[:200]}
        for label, data in cases.items():
            with self.subTest(label), self.assertRaises(KernelArtifactError):
                inspect_module(data)

    def test_symbol_list(self):
        self.assertEqual(parse_symbol_list(SYMBOL_LIST),
                         {"kmalloc_caches", "printk", "__traceiter_android_vh_foo", "dma_buf_export"})
        self.assertEqual(parse_symbol_list("[abi_symbol_list]\n# nothing yet\n"), set())
        with self.assertRaises(KernelArtifactError):
            parse_symbol_list("printk extra\n")

    def test_check_modules(self):
        core = inspect_module(build_module("vendor_core", undefined=("printk",), exports=("vendor_helper",)))
        wlan = inspect_module(build_module("wlan", undefined=("printk", "vendor_helper", "ion_alloc", "ion_free"),
                                           vermagic="6.1.75-android14-11 SMP aarch64"))
        odd = inspect_module(build_module("odd", vermagic="5.4.0-custom SMP"))
        report = check_modules([core, wlan, odd], parse_symbol_list(SYMBOL_LIST), "android17-6.18")
        self.assertEqual(report.missing, {"ion_alloc": ["wlan"], "ion_free": ["wlan"]})
        self.assertEqual(report.rebuild_required, ["wlan"])
        self.assertEqual(report.unknown_vermagic, ["odd"])


class UprevTests(unittest.TestCase):
    def setUp(self):
        self.kb = load_kb()
        self.r17 = release_entry(self.kb, "17")

    def test_candidates_are_not_older_than_current(self):
        c = uprev_candidates(self.kb, self.r17, "android14-6.1", AS_OF, date(2030, 1, 1))
        self.assertEqual([x["branch"] for x in c], ["android17-6.18", "android16-6.12", "android15-6.6",
                                                   "android14-6.1"])
        self.assertEqual([x["covers_support_until"] for x in c], [True, False, False, False])
        self.assertTrue(c[-1]["is_current"])
        self.assertEqual(recommended_uprev(c)["branch"], "android17-6.18")

    def test_recommendation_skips_qpr_dropped_kernels(self):
        c = uprev_candidates(self.kb, self.r17, "android12-5.10", AS_OF)
        dropped = {x["branch"] for x in c if x["unsupported_from"]}
        self.assertEqual(dropped, {"android12-5.10", "android13-5.10"})
        self.assertEqual(recommended_uprev(c)["branch"], "android13-5.15")
        self.assertIsNone(recommended_uprev(uprev_candidates(self.kb, self.r17, "android12-5.10", date(2031, 1, 1))))

    def test_recommendation_falls_back_to_latest_eol(self):
        c = uprev_candidates(self.kb, self.r17, "android14-6.1", AS_OF, date(2031, 12, 31))
        best = recommended_uprev(c)
        self.assertEqual((best["branch"], best["covers_support_until"]), ("android17-6.18", False))


class KernelReadinessTests(unittest.TestCase):
    def profile(self, branch="android14-6.1", **kw):
        return PlatformProfile("p", "16", branch, supports_16kb=True, sepolicy_memfd_ready=True, **kw)

    def test_uprev_hint_in_kernel_findings(self):
        result = evaluate(self.profile("android13-5.10"), "17", AS_OF)
        qpr = next(f for f in result["findings"] if f["rule_id"] == "KERNEL_COMPAT_QPR")
        self.assertIn("권장 uprev 대상: android13-5.15", qpr["detail"])
        self.assertEqual(result["kernel_branch"], "android13-5.10")

    def test_planned_kernel_changes_kernel_rules(self):
        p = self.profile("android13-5.10", support_until=date(2030, 1, 1))
        self.assertIn("KERNEL_EOL", rule_ids(evaluate(p, "17", AS_OF)))
        result = evaluate(p, "17", AS_OF, target_kernel_branch="android17-6.18")
        self.assertEqual(rule_ids(result), ["KERNEL_UPREV_PLANNED"])
        self.assertEqual(result["kernel_branch"], "android17-6.18")
        with self.assertRaises(ValueError):
            evaluate(self.profile("android16-6.12"), "17", AS_OF, target_kernel_branch="android14-6.1")

    def test_kmi_findings(self):
        mods = [inspect_module(build_module("wlan", undefined=("printk", "ion_alloc"),
                                            vermagic="6.1.75-android14-11 SMP aarch64"))]
        result = evaluate(self.profile(), "17", AS_OF, target_kernel_branch="android17-6.18",
                          kernel_modules=mods, kmi_symbols=parse_symbol_list(SYMBOL_LIST))
        self.assertTrue(result["ready"])
        self.assertEqual(rule_ids(result, "warning"), ["KMI_SYMBOL_MISSING"])
        self.assertIn("ion_alloc", result["findings"][0]["title"])
        self.assertIn("KERNEL_MODULE_REBUILD", rule_ids(result, "info"))

    def test_many_missing_symbols_are_capped(self):
        mods = [inspect_module(build_module("big", undefined=tuple(f"sym_{i:03}" for i in range(30))))]
        result = evaluate(self.profile("android17-6.18"), "17", AS_OF, kernel_modules=mods,
                          kmi_symbols={"printk"})
        missing = [f for f in result["findings"] if f["rule_id"] == "KMI_SYMBOL_MISSING"]
        self.assertEqual(len(missing), 21)
        self.assertIn("10개", missing[-1]["title"])


if __name__ == "__main__":
    unittest.main()
