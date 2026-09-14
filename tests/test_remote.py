import os
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.test_ota_package import build_zip
from upgrade_core.ota_package import inspect_ota_package
from upgrade_core.remote import HttpRangeFile, RangeNotSupported

# P0: 공개 Pixel OTA 로 실패키지 검증 (네트워크 필요) — ANDROID_OS_NETWORK_TESTS=1
PIXEL_OTA = "https://dl.google.com/dl/android/aosp/lynx-ota-cp2a.260705.006-f4d6d546.zip"


def serve(body: bytes, support_range: bool):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("Range", ""))
            if support_range and match:
                start, end = int(match[1]), min(int(match[2]), len(body) - 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
                chunk = body[start:end + 1]
            else:
                self.send_response(200)
                chunk = body
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
            self.close_connection = True

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/ota.zip"


def stop(server):
    server.shutdown()
    server.server_close()


class HttpRangeFileTests(unittest.TestCase):
    def test_remote_inspection_matches_local(self):
        buf, _ = build_zip(payload=b"CrAU" + os.urandom(300_000))
        raw = buf.getvalue()
        server, url = serve(raw, support_range=True)
        self.addCleanup(stop, server)
        remote = HttpRangeFile(url, block_size=4096)
        info = inspect_ota_package(remote, compute_sha256=False)
        local = inspect_ota_package(buf)
        self.assertTrue(info.ready, info.reject_reasons)
        self.assertEqual((info.payload_offset, info.payload_size, info.streaming_property_files, info.file_size),
                         (local.payload_offset, local.payload_size, local.streaming_property_files, len(raw)))
        self.assertLess(remote.bytes_fetched, len(raw) // 2)  # 전체를 받지 않는다

    def test_read_semantics(self):
        body = bytes(range(256)) * 40
        server, url = serve(body, support_range=True)
        self.addCleanup(stop, server)
        f = HttpRangeFile(url, block_size=1000)
        f.seek(995)
        self.assertEqual(f.read(10), body[995:1005])
        f.seek(-3, 2)
        self.assertEqual(f.read(), body[-3:])
        self.assertEqual(f.read(5), b"")

    def test_origin_without_range_is_rejected(self):
        server, url = serve(b"x" * 100, support_range=False)
        self.addCleanup(stop, server)
        with self.assertRaises(RangeNotSupported):
            HttpRangeFile(url)


@unittest.skipUnless(os.environ.get("ANDROID_OS_NETWORK_TESTS"), "set ANDROID_OS_NETWORK_TESTS=1")
class PixelOtaTests(unittest.TestCase):
    def test_public_pixel_full_ota(self):
        f = HttpRangeFile(PIXEL_OTA, block_size=1 << 18)
        info = inspect_ota_package(f, compute_sha256=False)
        self.assertTrue(info.ready, info.reject_reasons)
        self.assertEqual(info.package_type, "full")
        self.assertEqual(info.pre_device, ["lynx"])
        self.assertEqual(info.post_sdk_level, 37)
        self.assertEqual(info.post_spl, "2026-07-05")
        self.assertIn("ota-streaming-property-files", info.metadata)
        self.assertLess(f.bytes_fetched, 2_000_000)


if __name__ == "__main__":
    unittest.main()
