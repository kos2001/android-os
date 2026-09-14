import unittest

from upgrade_core.matcher import DeviceState, Match, NoMatch, Package, Rollout, select_update
from upgrade_core.rollout import (RolloutWindow, boot_outcome, bucket, decode_error_code, evaluate_halt,
                                  in_rollout)

SRC = "vendor/pony/pony:16/BP2A/1:user/release-keys"
OLD = "vendor/pony/pony:15/AP4A/0:user/release-keys"
DST = "vendor/pony/pony:17/CP2A/2:user/release-keys"

FULL = Package(1, "full", ("pony",), (), DST, 2000, "2026-07-05")
DELTA = Package(2, "incremental", ("pony",), (SRC,), DST, 2000, "2026-07-05")


def device(**kw):
    base = dict(device="pony", fingerprint=SRC, build_timestamp=1000, security_patch="2026-06-05",
                channel="stable", device_hash="a" * 64, carrier="KT")
    base.update(kw)
    return DeviceState(**base)


def rollout(**kw):
    base = dict(id=41, channel="stable", state="active", percent=100.0, target_build=DST,
                packages=(FULL, DELTA))
    base.update(kw)
    return Rollout(**base)


class MatcherTests(unittest.TestCase):
    def test_incremental_preferred_when_source_matches(self):
        result = select_update([rollout()], device())
        self.assertIsInstance(result, Match)
        self.assertEqual(result.package.id, 2)

    def test_full_fallback_for_unknown_source(self):
        result = select_update([rollout()], device(fingerprint=OLD))
        self.assertEqual(result.package.id, 1)

    def test_up_to_date(self):
        self.assertEqual(select_update([rollout()], device(fingerprint=DST)), NoMatch("UP_TO_DATE"))

    def test_timestamp_or_spl_regression_blocked(self):
        self.assertEqual(select_update([rollout()], device(build_timestamp=3000)), NoMatch("NO_COMPATIBLE_PACKAGE"))
        self.assertEqual(select_update([rollout()], device(security_patch="2026-08-01")),
                         NoMatch("NO_COMPATIBLE_PACKAGE"))

    def test_other_device_gets_nothing(self):
        self.assertEqual(select_update([rollout()], device(device="tail")), NoMatch("NO_COMPATIBLE_PACKAGE"))

    def test_filters_channel_and_state(self):
        self.assertEqual(select_update([rollout(filters={"carriers": ["SKT"]})], device()), NoMatch("UP_TO_DATE"))
        self.assertEqual(select_update([rollout(channel="beta")], device()), NoMatch("UP_TO_DATE"))
        self.assertEqual(select_update([rollout(state="halted")], device()), NoMatch("ROLLOUT_HALTED"))
        self.assertEqual(select_update([rollout(state="draft")], device()), NoMatch("UP_TO_DATE"))

    def test_zero_percent_is_not_in_rollout(self):
        self.assertEqual(select_update([rollout(percent=0)], device()), NoMatch("NOT_IN_ROLLOUT"))


class RolloutTests(unittest.TestCase):
    def test_bucket_is_deterministic_and_ranged(self):
        self.assertEqual(bucket(1, "abc"), bucket(1, "abc"))
        self.assertTrue(all(0 <= bucket(7, f"d{i}") < 10_000 for i in range(200)))

    def test_raising_percent_keeps_existing_devices(self):
        devices = [f"device-{i}" for i in range(5000)]
        at5 = {d for d in devices if in_rollout(9, d, 5)}
        at25 = {d for d in devices if in_rollout(9, d, 25)}
        self.assertTrue(at5 <= at25)
        self.assertAlmostEqual(len(at25) / len(devices), 0.25, delta=0.03)
        self.assertEqual(sum(in_rollout(9, d, 100) for d in devices), len(devices))

    def test_bucket_independent_across_rollouts(self):
        devices = [f"device-{i}" for i in range(2000)]
        a = {d for d in devices if in_rollout(1, d, 10)}
        b = {d for d in devices if in_rollout(2, d, 10)}
        self.assertLess(len(a & b), len(a) * 0.5)

    def test_percent_range_validated(self):
        with self.assertRaises(ValueError):
            in_rollout(1, "x", 101)

    def test_decode_error_code(self):
        e = decode_error_code(1073741833)  # Resumed | DownloadTransferError
        self.assertEqual((e.base, e.flags, e.name), (9, ("Resumed",), "DownloadTransferError"))
        e = decode_error_code(-2147483588)  # DevMode(1<<31) | 60 as signed Java int
        self.assertEqual((e.base, e.flags, e.name), (60, ("DevMode",), "NotEnoughSpace"))
        self.assertEqual(decode_error_code(2404).name, "HttpResponse404")

    def test_boot_outcome(self):
        self.assertEqual(boot_outcome(DST, SRC, DST), "boot_success")
        self.assertEqual(boot_outcome(SRC, SRC, DST), "boot_fallback")
        self.assertIsNone(boot_outcome(OLD, SRC, DST))

    def test_evaluate_halt(self):
        rules = {"min_sample": 100, "max_error_rate": 0.03, "max_boot_fallback_rate": 0.005,
                 "max_error_code_rate": {"60": 0.02}}
        ok = evaluate_halt(RolloutWindow(attempted=1000, failed_by_code={48: 200, 9: 10}), rules)
        self.assertFalse(ok.halt, ok.reasons)  # 사용자 취소(48)는 실패로 세지 않음
        bad = evaluate_halt(RolloutWindow(attempted=1000, failed_by_code={60: 25, 9: 10},
                                          installed=900, boot_fallback=9), rules)
        self.assertTrue(bad.halt)
        self.assertEqual(len(bad.reasons), 3)
        small = evaluate_halt(RolloutWindow(attempted=10, failed_by_code={9: 10}), rules)
        self.assertFalse(small.halt)


if __name__ == "__main__":
    unittest.main()
