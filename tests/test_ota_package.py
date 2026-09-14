import base64
import hashlib
import io
import unittest
import zipfile

from upgrade_core.ota_package import (OtaPackageError, inspect_ota_package, parse_key_values,
                                      parse_property_files)

SRC = "vendor/pony/pony:16/BP2A.250605.031/13101520:user/release-keys"
DST = "vendor/pony/pony:17/CP2A.260705.012/14200001:user/release-keys"


def build_zip(*, payload=b"CrAU" + b"\x00" * 2048, pre_build=SRC, ota_type="AB", downgrade=False,
              compress_payload=False, file_size=None, streaming_override=None, drop=(), metadata_hash=None):
    b64 = lambda data: base64.b64encode(hashlib.sha256(data).digest()).decode()  # noqa: E731
    props = "\n".join([
        f"FILE_HASH={b64(payload)}",
        f"FILE_SIZE={len(payload) if file_size is None else file_size}",
        f"METADATA_HASH={metadata_hash or b64(payload[:512])}",
        "METADATA_SIZE=512",
    ]) + "\n"
    meta = {
        "ota-type": ota_type, "pre-device": "pony", "post-build": DST,
        "post-build-incremental": "14200001", "post-timestamp": "1783000000",
        "post-security-patch-level": "2026-07-05", "post-sdk-level": "37",
    }
    if pre_build:
        meta["pre-build"] = pre_build
    if downgrade:
        meta["ota-downgrade"] = "yes"
    if streaming_override:
        meta["ota-streaming-property-files"] = streaming_override
    for key in drop:
        meta.pop(key, None)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo("payload.bin"), payload,
                    compress_type=zipfile.ZIP_DEFLATED if compress_payload else zipfile.ZIP_STORED)
        zf.writestr(zipfile.ZipInfo("payload_properties.txt"), props, compress_type=zipfile.ZIP_STORED)
        zf.writestr(zipfile.ZipInfo("care_map.pb"), b"care", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/com/android/metadata", "\n".join(f"{k}={v}" for k, v in meta.items()),
                    compress_type=zipfile.ZIP_DEFLATED)
    buf.seek(0)
    return buf, payload


class ParseTests(unittest.TestCase):
    def test_key_values_split_on_first_equals(self):
        self.assertEqual(parse_key_values("A=b=c\n\nX = 1\n"), {"A": "b=c", "X": "1"})

    def test_key_values_rejects_garbage(self):
        with self.assertRaises(OtaPackageError):
            parse_key_values("no-equals-here")

    def test_property_files_with_padding(self):
        parsed = parse_property_files("payload.bin:679:343,metadata:69:379          ")
        self.assertEqual(parsed, {"payload.bin": (679, 343), "metadata": (69, 379)})


class InspectTests(unittest.TestCase):
    def test_incremental_package_offsets_point_at_payload_bytes(self):
        buf, payload = build_zip()
        info = inspect_ota_package(buf)
        self.assertTrue(info.ready, info.reject_reasons)
        self.assertEqual(info.package_type, "incremental")
        self.assertEqual(info.pre_builds, [SRC])
        self.assertEqual(info.pre_device, ["pony"])
        raw = buf.getvalue()
        self.assertEqual(raw[info.payload_offset:info.payload_offset + info.payload_size], payload)
        self.assertEqual(info.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(info.file_size, len(raw))
        names = [item.split(":")[0] for item in info.streaming_property_files.split(",")]
        self.assertEqual(names, ["payload.bin", "payload_properties.txt", "care_map.pb"])
        self.assertTrue(info.apply_payload_headers()[0].startswith("FILE_HASH="))

    def test_streaming_entries_are_readable_by_offset(self):
        buf, _ = build_zip()
        info = inspect_ota_package(buf)
        raw = buf.getvalue()
        for name, (offset, size) in parse_property_files(info.streaming_property_files).items():
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                self.assertEqual(raw[offset:offset + size], zf.read(name), name)

    def test_full_package_and_multi_sku_pre_build(self):
        buf, _ = build_zip(pre_build=None)
        self.assertEqual(inspect_ota_package(buf).package_type, "full")
        buf, _ = build_zip(pre_build=f"{SRC}|vendor/pony/pony_kr:16/X/1:user/release-keys")
        self.assertEqual(len(inspect_ota_package(buf).pre_builds), 2)

    def test_rejections(self):
        cases = {
            "compressed payload": (dict(compress_payload=True), "ZIP_STORED"),
            "non-AB": (dict(ota_type="BLOCK"), "only AB"),
            "downgrade": (dict(downgrade=True), "ota-downgrade"),
            "size mismatch": (dict(file_size=1), "FILE_SIZE"),
            "metadata offset mismatch": (dict(streaming_override="payload.bin:1:2,payload_properties.txt:3:4"),
                                         "payload.bin location"),
            "missing post-timestamp": (dict(drop=("post-timestamp",)), "post-timestamp"),
            "metadata hash mismatch": (dict(metadata_hash="AAAA"), "METADATA_HASH mismatch"),
            "bad magic": (dict(payload=b"XXXX" + b"\x00" * 2048), "CrAU"),
        }
        for label, (kwargs, needle) in cases.items():
            with self.subTest(label):
                buf, _ = build_zip(**kwargs)
                info = inspect_ota_package(buf)
                self.assertFalse(info.ready)
                self.assertTrue(any(needle in r for r in info.reject_reasons), info.reject_reasons)

    def test_structural_errors(self):
        with self.assertRaises(OtaPackageError):
            inspect_ota_package(io.BytesIO(b"not a zip"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("payload.bin", b"x")
        buf.seek(0)
        with self.assertRaisesRegex(OtaPackageError, "missing zip entry"):
            inspect_ota_package(buf)


if __name__ == "__main__":
    unittest.main()
