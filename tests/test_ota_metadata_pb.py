import unittest
from pathlib import Path

from upgrade_core.ota_metadata_pb import ProtoError, cross_check, fields, parse_ota_metadata
from upgrade_core.ota_package import parse_key_values

FIX = Path(__file__).parent / "fixtures" / "ota"


class RealMetadataPbTests(unittest.TestCase):
    """공개 OTA 패키지에서 추출한 실제 metadata(.pb) — tests/fixtures/ota/README.md."""

    def test_pixel_full_package(self):
        pb = parse_ota_metadata((FIX / "lynx-cp2a.260705.006.metadata.pb").read_bytes())
        self.assertEqual((pb.type, pb.wipe, pb.downgrade, pb.spl_downgrade), ("AB", False, False, False))
        self.assertEqual(pb.precondition.device, ["lynx"])
        self.assertEqual(pb.precondition.build, [])
        self.assertEqual(pb.postcondition.build, ["google/lynx/lynx:17/CP2A.260705.006/15641320:user/release-keys"])
        self.assertEqual((pb.postcondition.timestamp, pb.postcondition.sdk_level,
                          pb.postcondition.security_patch_level), (1781499293, "37", "2026-07-05"))
        text = parse_key_values((FIX / "lynx-cp2a.260705.006.metadata").read_text())
        self.assertEqual(cross_check(text, pb), [])

    def test_real_incremental_package(self):
        pb = parse_ota_metadata((FIX / "tokay-incremental-2026090700-2026091000.metadata.pb").read_bytes())
        self.assertEqual(pb.precondition.build, ["google/tokay/tokay:17/CP2A.260805.005/2026090700:user/release-keys"])
        self.assertEqual(pb.precondition.build_incremental, "2026090700")
        self.assertEqual(pb.postcondition.build_incremental, "2026091000")

    def test_cross_check_detects_disagreement(self):
        pb = parse_ota_metadata((FIX / "lynx-cp2a.260705.006.metadata.pb").read_bytes())
        text = parse_key_values((FIX / "lynx-cp2a.260705.006.metadata").read_text())
        tampered = {**text, "post-timestamp": "1", "ota-downgrade": "yes"}
        reasons = cross_check(tampered, pb)
        self.assertEqual(len(reasons), 2)
        self.assertTrue(any("post-timestamp" in r for r in reasons))

    def test_malformed_buffers(self):
        for bad in (b"\x0a\x05ab", b"\xff", b"\x0b"):
            with self.subTest(bad=bad), self.assertRaises(ProtoError):
                fields(bad)


if __name__ == "__main__":
    unittest.main()
