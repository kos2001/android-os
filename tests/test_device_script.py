import importlib.util
import shlex
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "device_ota_test", Path(__file__).resolve().parent.parent / "scripts" / "device_ota_test.py")
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)

PROPS = {"device": "lynx", "fingerprint": "google/lynx/lynx:16/BP4A.260205.001/14624666:user/release-keys",
         "incremental": "14624666", "build_timestamp": "1766287731", "security_patch": "2026-02-05",
         "sdk_level": "36", "slot_suffix": "_a", "serial": "ABC123",
         "boot_id": "6f1c2e4a-9b3d-4c5e-8f7a-1b2c3d4e5f60"}


class DeviceScriptTests(unittest.TestCase):
    def test_check_request_hashes_serial(self):
        req = script.build_check_request(PROPS, "testing", "salt")
        self.assertEqual((req["build_timestamp"], req["sdk_level"], req["channel"]), (1766287731, 36, "testing"))
        self.assertNotIn("ABC123", str(req))
        self.assertEqual(len(req["device_hash"]), 64)
        self.assertEqual(req["boot_id"], PROPS["boot_id"])
        self.assertEqual(script.event(3, 2, "updated_need_reboot", boot_id="b")["attempt"], 2)
        with self.assertRaises(ValueError):
            script.build_check_request({**PROPS, "fingerprint": ""}, "testing", "salt")

    def test_install_command_round_trips_through_remote_shell(self):
        headers = ["FILE_HASH=0famP/45n5lraKcwexYhzS5spGQ5I8aYULN70kYSLmo=", "FILE_SIZE=3158523261",
                   "METADATA_HASH=ynnKoDuCIOzwLIKGJLIA4z9zccKwT1tNQYYl85xUY+c=", "METADATA_SIZE=196619"]
        update = {"package": {"url": "https://dl.google.com/x.zip?a=1&b=2", "payload_offset": 4534,
                              "payload_size": 3158523261, "headers": headers}}
        argv = shlex.split(script.install_command(update))  # 원격 sh 파싱 모사
        self.assertEqual(argv[:3], ["update_engine_client", "--update", "--follow"])
        self.assertIn("--payload=https://dl.google.com/x.zip?a=1&b=2", argv)
        self.assertIn("--offset=4534", argv)
        headers_arg = next(a for a in argv if a.startswith("--headers="))
        self.assertEqual(headers_arg.removeprefix("--headers=").split("\n"), headers)


if __name__ == "__main__":
    unittest.main()
