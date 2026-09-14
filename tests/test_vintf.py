import unittest
from datetime import date
from pathlib import Path

from upgrade_core.readiness import PlatformProfile, evaluate
from upgrade_core.vintf import (Version, VersionRange, VintfError, check_manifest, diff_matrices, parse_manifest,
                                parse_matrix)

FIX = Path(__file__).parent / "fixtures" / "vintf"
read = lambda name: (FIX / name).read_text(encoding="utf-8")  # noqa: E731
BASE8 = '<manifest version="1.0" type="device" target-level="8"/>'
HIDL_MAPPER = ('<manifest version="1.0" type="device"><hal format="hidl">'
               '<name>android.hardware.graphics.mapper</name><transport arch="32+64">passthrough</transport>'
               '<fqname>@4.0::IMapper/default</fqname></hal></manifest>')


class VersionTests(unittest.TestCase):
    def test_supported_by_matches_libvintf(self):
        r = VersionRange(2, 3, 7)
        self.assertTrue(r.supported_by(Version(2, 8)))   # 상한 미검사 (VersionRange.h 주석 예시)
        self.assertTrue(r.supported_by(Version(2, 3)))
        self.assertFalse(r.supported_by(Version(2, 2)))
        self.assertFalse(r.supported_by(Version(3, 5)))


class RealMatrixTests(unittest.TestCase):
    """android-16.0.0_r4 / android-17.0.0_r1 태그의 실제 compatibility matrix."""

    @classmethod
    def setUpClass(cls):
        cls.a16 = parse_matrix(read("a16.202504.xml"))
        cls.a17 = parse_matrix(read("a17.202604.xml"))
        cls.l8 = parse_matrix(read("a17.8.xml"))

    def test_levels_and_hal_counts(self):
        self.assertEqual((self.a16.level, self.a17.level, self.l8.level), ("202504", "202604", "8"))
        self.assertFalse(any(fmt == "hidl" for fmt, _ in self.a17.hals))
        self.assertTrue(any(fmt == "hidl" for fmt, _ in self.l8.hals))

    def test_diff_android16_to_17(self):
        d = diff_matrices(self.a16, self.a17)
        self.assertIn("android.hardware.bluetooth.gatt (aidl)", d.added)
        self.assertEqual(d.removed, ["android.hardware.health.storage (aidl)"])
        audio = next(c for c in d.changed if c["hal"] == "android.hardware.audio.core (aidl)")
        self.assertEqual((audio["versions_before"], audio["versions_after"]), (["1-3"], ["1-4"]))

    def test_hidl_hals_gone_from_latest_level(self):
        removed = diff_matrices(self.l8, self.a17).removed
        for hal in ("android.hardware.audio (hidl)", "android.hardware.graphics.mapper (hidl)",
                    "android.hardware.bluetooth (hidl)"):
            self.assertIn(hal, removed)

    def test_manifest_fragments_against_matrices(self):
        m = parse_manifest(BASE8, read("frag.health.xml"), read("frag.vib.xml"), HIDL_MAPPER)
        self.assertEqual(m.target_level, "8")
        self.assertIn("android.hardware.health@5::IHealth/default", [h.fqname for h in m.hals])
        self.assertEqual(check_manifest(m, self.l8), [])
        issues = check_manifest(m, self.a17)
        self.assertEqual([(i.kind, i.hal) for i in issues],
                         [("NOT_IN_MATRIX", "android.hardware.graphics.mapper@4.0::IMapper/default")])

    def test_version_and_instance_issues(self):
        old = parse_manifest('<manifest version="1.0" type="device"><hal format="aidl">'
                             '<name>android.hardware.health</name><version>1</version>'
                             '<fqname>IHealth/default</fqname><fqname>IHealth/backup</fqname></hal></manifest>')
        kinds = {(i.kind, i.hal) for i in check_manifest(old, self.a17)}
        self.assertIn(("VERSION_UNSUPPORTED", "android.hardware.health@1::IHealth/default"), kinds)


class ParseErrorTests(unittest.TestCase):
    def test_errors(self):
        with self.assertRaises(VintfError):
            parse_manifest("<not-a-manifest/>")
        with self.assertRaises(VintfError):
            parse_manifest('<manifest type="framework"/>')
        with self.assertRaises(VintfError):
            parse_manifest(BASE8, '<manifest type="device" target-level="7"/>')
        with self.assertRaises(VintfError):
            parse_matrix('<compatibility-matrix type="device"/>')
        with self.assertRaises(VintfError):
            parse_manifest('<manifest type="device"><hal format="aidl"><name>x</name><fqname>bad</fqname></hal></manifest>')


class ReadinessFcmTests(unittest.TestCase):
    def profile(self, level):
        return PlatformProfile("p", "16", "android16-6.12", fcm_target_level=level, supports_16kb=True,
                               sepolicy_memfd_ready=True)

    def test_removed_level_is_blocker(self):
        result = evaluate(self.profile("6"), "17", date(2026, 9, 14))
        self.assertEqual([f["rule_id"] for f in result["findings"]], ["FCM_LEVEL_REMOVED"])
        self.assertIn("refs/tags/android-17.0.0_r1", result["findings"][0]["sources"][0])

    def test_supported_level_passes_and_manifest_findings_attached(self):
        self.assertTrue(evaluate(self.profile("8"), "17", date(2026, 9, 14))["ready"])
        manifest = parse_manifest(BASE8, HIDL_MAPPER)
        result = evaluate(self.profile("8"), "17", date(2026, 9, 14), manifest=manifest,
                          target_matrix=parse_matrix(read("a17.202604.xml")))
        self.assertTrue(result["ready"])
        self.assertEqual([f["rule_id"] for f in result["findings"]], ["HAL_NOT_IN_MATRIX"])


if __name__ == "__main__":
    unittest.main()
