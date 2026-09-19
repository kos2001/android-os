"""finding 문구의 한국어·영어 동시 제공과 기존 DB 마이그레이션."""
import re
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests.elf_builder import build_module
from upgrade_core.kernel import inspect_module
from upgrade_core.readiness import Hal, PlatformProfile, evaluate
from upgrade_core.vintf import parse_manifest, parse_matrix

try:
    from backend.store import Store
except ImportError:  # 코어만 설치된 환경
    Store = None

HANGUL = re.compile("[가-힣]")
FIX = Path(__file__).parent / "fixtures" / "vintf"
MANIFEST = ('<manifest version="1.0" type="device" target-level="8"><hal format="aidl">'
            '<name>android.hardware.nope</name><fqname>IFoo/default</fqname></hal></manifest>')


def every_rule() -> list[dict]:
    """가능한 한 많은 규칙을 한 번에 발생시킨다."""
    legacy = PlatformProfile("legacy", "14", "android13-5.10", fcm_target_level="4", uses_vndk=True, uses_ion=True,
                             support_until=date(2031, 1, 1), hals=[Hal("android.hardware.foo", "hidl", "1.0")])
    mods = [inspect_module(build_module("m", undefined=tuple(f"s{i}" for i in range(25)),
                                        vermagic="5.15.1-android13-1 SMP")),
            inspect_module(build_module("odd", vermagic="5.4.0-custom"))]
    findings = evaluate(legacy, "17", date(2026, 9, 14), target_kernel_branch="android14-6.1",
                        kernel_modules=mods, kmi_symbols=set(),
                        manifest=parse_manifest(MANIFEST), target_matrix=parse_matrix((FIX / "a17.8.xml").read_text()))
    findings = findings["findings"]
    findings += evaluate(PlatformProfile("x", "16", "android99-9.9"), "17", date(2026, 9, 14))["findings"]
    findings += evaluate(PlatformProfile("y", "16", "android12-5.10"), "17-QPR1", date(2028, 1, 1))["findings"]
    findings += evaluate(PlatformProfile("z", "16", "android16-6.12", fcm_target_level="99"), "17",
                         date(2026, 9, 14))["findings"]
    return findings


class BilingualFindingTests(unittest.TestCase):
    def test_every_finding_has_both_languages(self):
        findings = every_rule()
        rules = {f["rule_id"] for f in findings}
        self.assertTrue({"KERNEL_COMPAT", "KERNEL_EOL", "KERNEL_UNKNOWN", "KERNEL_UPREV_PLANNED", "KMI_SYMBOL_MISSING",
                         "KERNEL_MODULE_REBUILD", "KERNEL_MODULE_VERMAGIC", "ION_REMOVED", "VNDK_DEPRECATED",
                         "SEPOLICY_MEMFD", "HIDL_HALS", "PAGE_16KB", "FCM_LEVEL_REMOVED", "FCM_LEVEL_UNKNOWN",
                         "HAL_NOT_IN_MATRIX"} <= rules, rules)
        for f in findings:
            with self.subTest(f["rule_id"], title=f["title"]):
                self.assertTrue(f["title_en"] and f["detail_en"])
                self.assertIsNone(HANGUL.search(f["title_en"] + f["detail_en"]))
        self.assertTrue(any(HANGUL.search(f["title"]) for f in findings))

    def test_uprev_hint_is_translated(self):
        f = next(f for f in evaluate(PlatformProfile("p", "16", "android13-5.10"), "17", date(2026, 9, 14))["findings"]
                 if f["rule_id"] == "KERNEL_COMPAT_QPR")
        self.assertIn("권장 uprev 대상: android13-5.15", f["detail"])
        self.assertIn("Recommended uprev: android13-5.15", f["detail_en"])


@unittest.skipIf(Store is None, "backend deps not installed (use .venv)")
class MigrationTests(unittest.TestCase):
    def test_old_database_gains_english_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE platform (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, soc TEXT NOT NULL,
                    android_version TEXT NOT NULL, kernel_branch TEXT NOT NULL, fcm_target_level TEXT,
                    uses_vndk INTEGER NOT NULL DEFAULT 0, uses_ion INTEGER NOT NULL DEFAULT 0,
                    supports_16kb INTEGER NOT NULL DEFAULT 0, sepolicy_memfd_ready INTEGER NOT NULL DEFAULT 0,
                    support_until TEXT, created_at TEXT NOT NULL);
                CREATE TABLE readiness_run (id INTEGER PRIMARY KEY, platform_id INTEGER NOT NULL, target_release TEXT,
                    kb_version TEXT NOT NULL, summary TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE finding (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, rule_id TEXT NOT NULL,
                    severity TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL, sources TEXT NOT NULL);
                INSERT INTO platform VALUES (1, 'p', 's', '16', 'android16-6.12', NULL, 0, 0, 0, 0, NULL, 'now');
                INSERT INTO readiness_run VALUES (1, 1, '17', 'kb', '{"ready": true, "counts": {}, "as_of": "2026-09-14",
                    "current_release": "16"}', 'dev', 'now');
                INSERT INTO finding VALUES (1, 1, 'PAGE_16KB', 'info', '16 KB 페이지 미지원', '상세', '[]');
            """)
            conn.commit()
            conn.close()
            store = Store(path)
            self.addCleanup(store.close)
            run = store.get_run(1)
            self.assertEqual(run["findings"][0]["title"], "16 KB 페이지 미지원")
            self.assertIsNone(run["findings"][0]["title_en"])
            Store(path).close()  # 두 번째 열기에서도 마이그레이션이 멱등


if __name__ == "__main__":
    unittest.main()
