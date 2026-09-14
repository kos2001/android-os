"""코드 리뷰(2026-09-14) 지적 사항 회귀 테스트. 번호는 리뷰 순위."""
import io
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.test_ota_api import B1, BASE, OLD, check_body, dhash, ts
from tests.test_ota_package import DST, SRC, build_zip
from upgrade_core.ota_package import MAX_TEXT_ENTRY, OtaPackageError, inspect_ota_package
from upgrade_core.remote import HttpRangeFile, RangeNotSupported, RedirectRefused

try:
    from fastapi.testclient import TestClient

    from backend.app import create_app
    from backend.ota_api import https_range_opener
    from backend.store import Conflict, Store
except ImportError:
    TestClient = None

B3 = "11111111-2222-4333-8444-555555555555"


def serve(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/ota.zip"


def stop(server):
    server.shutdown()
    server.server_close()


class RemoteSafetyTests(unittest.TestCase):
    def test_3_redirects_are_refused(self):
        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data")
                self.send_header("Content-Length", "0")
                self.end_headers()
                self.close_connection = True

            def log_message(self, *a):
                pass

        server, url = serve(Redirect)
        self.addCleanup(stop, server)
        with self.assertRaises(RedirectRefused):
            HttpRangeFile(url)

    def test_4_origin_switching_to_full_body_is_rejected_without_reading_it(self):
        body = b"x" * 5_000_000

        class Switch(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.headers.get("Range") == "bytes=0-0":
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes 0-0/{len(body)}")
                    self.send_header("Content-Length", "1")
                    self.end_headers()
                    self.wfile.write(b"x")
                else:  # Range 무시하고 전체 본문
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    try:
                        self.wfile.write(body)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                self.close_connection = True

            def log_message(self, *a):
                pass

        server, url = serve(Switch)
        self.addCleanup(stop, server)
        f = HttpRangeFile(url, block_size=1024)
        with self.assertRaises(RangeNotSupported):
            f.read(10)
        self.assertEqual(f.bytes_fetched, 0)

    def test_4_cache_is_bounded(self):
        data = bytes(range(256)) * 400

        class Ok(BaseHTTPRequestHandler):
            def do_GET(self):
                start, end = map(int, self.headers["Range"].removeprefix("bytes=").split("-"))
                end = min(end, len(data) - 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                self.wfile.write(data[start:end + 1])
                self.close_connection = True

            def log_message(self, *a):
                pass

        server, url = serve(Ok)
        self.addCleanup(stop, server)
        f = HttpRangeFile(url, block_size=1000, cache_blocks=4)
        self.assertEqual(f.read(), data)
        self.assertLessEqual(len(f._cache), 4)

    def test_4_oversized_metadata_entry_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(zipfile.ZipInfo("payload.bin"), b"CrAU")
            zf.writestr(zipfile.ZipInfo("payload_properties.txt"), b"FILE_SIZE=4\n")
            zf.writestr("META-INF/com/android/metadata", b"a" * (MAX_TEXT_ENTRY + 10),
                        compress_type=zipfile.ZIP_DEFLATED)
        buf.seek(0)
        with self.assertRaisesRegex(OtaPackageError, "too large"):
            inspect_ota_package(buf)

    def test_8_malformed_zip_contents_raise_package_error(self):
        buf, _ = build_zip()
        raw = bytearray(buf.getvalue())
        buf2 = io.BytesIO()
        with zipfile.ZipFile(buf2, "w") as zf:
            with zipfile.ZipFile(io.BytesIO(bytes(raw))) as src:
                for info in src.infolist():
                    content = src.read(info)
                    if info.filename.endswith("metadata"):
                        content = b"\xff\xfe" + content
                    zf.writestr(info, content)
        buf2.seek(0)
        with self.assertRaisesRegex(OtaPackageError, "UTF-8"):
            inspect_ota_package(buf2)


@unittest.skipIf(TestClient is None, "fastapi not installed (use .venv)")
class OtaRegressionTests(unittest.TestCase):
    def setUp(self):
        self.packages = {BASE + "full.zip": build_zip(pre_build=None)[0].getvalue(),
                         BASE + "delta.zip": build_zip(pre_build=SRC)[0].getvalue()}
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.app = create_app(store=self.store, api_keys="", device_keys="", auto_halt_interval_s=0, dev_mode=True,
                              package_opener=lambda url: io.BytesIO(self.packages[url]))
        self.c = TestClient(self.app)
        for name in ("full.zip", "delta.zip"):
            self.assertEqual(self.c.post("/admin/v1/packages", json={"url": BASE + name}).status_code, 201)

    def rollout(self, name="r", **kw):
        body = {"name": name, "target_fingerprint": DST, "channel": "stable", "stages": [{"percent": 100}],
                "halt_rules": {"min_sample": 1, "max_error_rate": 0.5}}
        body.update(kw)
        rid = self.c.post("/admin/v1/rollouts", json=body).json()["id"]
        self.c.post(f"/admin/v1/rollouts/{rid}/start")
        return rid

    def check(self, device, **kw):
        return self.c.post("/device/v1/update-check", json=check_body(dhash(device), **kw)).json()

    def events(self, device, *events):
        return self.c.post("/device/v1/events", json={"device_hash": dhash(device), "events": list(events)})

    def test_2_failures_survive_retry_in_metrics(self):
        rid = self.rollout()
        a = self.check("d")
        self.events("d", {"assignment_id": a["assignment_id"], "type": "download_started", "occurred_at": ts()},
                    {"assignment_id": a["assignment_id"], "type": "error", "error_code": 60, "occurred_at": ts(1)})
        retry = self.check("d")
        self.assertEqual(retry["attempt"], 2)
        window = self.c.get(f"/admin/v1/rollouts/{rid}/metrics").json()["window"]
        self.assertEqual((window["attempted"], window["failed_by_code"]), (1, {"60": 1}))
        # 두 번째 시도 성공 → 시도 2건, 실패 1건 유지
        self.events("d", {"assignment_id": a["assignment_id"], "attempt": 2, "type": "updated_need_reboot",
                          "boot_id": B1, "occurred_at": ts(10)})
        self.check("d", fingerprint=DST, build_timestamp=1_783_000_000)
        window = self.c.get(f"/admin/v1/rollouts/{rid}/metrics").json()["window"]
        self.assertEqual((window["attempted"], window["installed"], window["failed_by_code"]), (2, 1, {"60": 1}))

    def test_5_transition_does_not_overwrite_concurrent_halt(self):
        rid = self.rollout(stages=[{"percent": 10, "min_soak_hours": 0}, {"percent": 100, "min_soak_hours": 0}])
        ota = self.app.state.ota
        original = ota.get_rollout
        calls = {"n": 0}

        def racing_get(r):  # promote 가 active 를 읽은 직후 다른 스레드가 halt 했다고 가정
            result = original(r)
            calls["n"] += 1
            if calls["n"] == 1:
                with self.store.tx() as conn:
                    conn.execute("UPDATE rollout SET state = 'halted', halt_reason = 'x' WHERE id = ?", (r,))
            return result

        ota.get_rollout = racing_get
        try:
            with self.assertRaises(Conflict):
                ota.transition(rid, "promote", "rm")
        finally:
            ota.get_rollout = original
        self.assertEqual(ota.get_rollout(rid)["state"], "halted")

    def test_6_events_without_assignment_are_deduplicated(self):
        event = {"type": "status", "update_status": 3, "occurred_at": ts()}
        self.assertEqual(self.events("d", event).json(), {"accepted": 1, "duplicates": 0})
        self.assertEqual(self.events("d", event).json(), {"accepted": 0, "duplicates": 1})

    def test_7_rejected_batch_writes_nothing(self):
        self.rollout()
        a = self.check("d")
        foreign = self.check("other")
        batch = [{"assignment_id": a["assignment_id"], "type": "download_started", "occurred_at": ts()},
                 {"assignment_id": foreign["assignment_id"], "type": "download_started", "occurred_at": ts()}]
        self.assertEqual(self.events("d", *batch).status_code, 404)
        self.assertEqual(self.events("d", batch[0]).json(), {"accepted": 1, "duplicates": 0})

    def test_9_non_numeric_error_code_rule_rejected(self):
        r = self.c.post("/admin/v1/rollouts", json={
            "name": "bad", "target_fingerprint": DST, "channel": "stable", "stages": [{"percent": 1}],
            "halt_rules": {"max_error_code_rate": {"NotEnoughSpace": 0.1}}})
        self.assertEqual(r.status_code, 422)

    def test_10_in_progress_assignment_wins_over_newer_or_paused_rollout(self):
        first = self.rollout("first")
        a = self.check("d")
        self.events("d", {"assignment_id": a["assignment_id"], "type": "download_started", "occurred_at": ts()})
        self.rollout("second")
        again = self.check("d")
        self.assertEqual((again["rollout"]["id"], again["assignment_id"]), (first, a["assignment_id"]))
        self.c.post(f"/admin/v1/rollouts/{first}/pause")
        paused = self.check("d")
        self.assertEqual(paused["rollout"]["id"], first)  # 다운로드 중인 기기는 일시정지돼도 계속

    def test_11_late_event_from_previous_attempt_does_not_change_state(self):
        rid = self.rollout()
        a = self.check("d")
        self.events("d", {"assignment_id": a["assignment_id"], "type": "error", "error_code": 9, "occurred_at": ts()})
        self.assertEqual(self.check("d")["attempt"], 2)
        self.events("d", {"assignment_id": a["assignment_id"], "attempt": 2, "type": "updated_need_reboot",
                          "boot_id": B1, "occurred_at": ts(20)})
        late = self.events("d", {"assignment_id": a["assignment_id"], "attempt": 1, "type": "error",
                                 "error_code": 10, "occurred_at": ts(5)})
        self.assertEqual(late.json()["accepted"], 1)
        self.assertEqual(self.c.get(f"/admin/v1/rollouts/{rid}").json()["assignments"],
                         {"installed_pending_reboot": 1})
        future = self.events("d", {"assignment_id": a["assignment_id"], "attempt": 9, "type": "status",
                                   "occurred_at": ts(30)})
        self.assertEqual(future.status_code, 409)

    def test_1_retry_limit(self):
        self.rollout(policy={"max_attempts": 1})
        a = self.check("d", fingerprint=OLD)
        self.events("d", {"assignment_id": a["assignment_id"], "type": "updated_need_reboot", "boot_id": B1,
                          "occurred_at": ts()})
        result = self.check("d", fingerprint=OLD, boot_id=B3)  # 재부팅했지만 이전 슬롯
        self.assertEqual(result["reason"], "RETRY_LIMIT_REACHED")

    def test_3_opener_blocks_private_hosts_in_restricted_mode(self):
        from fastapi import HTTPException
        opener = https_range_opener({"localhost"}, restrict=True)
        with self.assertRaises(HTTPException) as ctx:
            opener("https://localhost/ota.zip")
        self.assertEqual(ctx.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            opener("http://localhost/ota.zip")


if __name__ == "__main__":
    unittest.main()
