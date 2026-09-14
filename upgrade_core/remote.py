"""HTTP Range 로 원격 파일을 seekable 파일처럼 읽는다 (패키지 ingest, P0 검증).

OTA zip 은 수 GB 이지만 검사에 필요한 것은 중앙 디렉터리·metadata·payload_properties 뿐이므로
몇 번의 Range 요청으로 끝난다. 오리진이 Range 를 지원하지 않으면 update_engine 스트리밍도
불가능하므로(NF-03) 여기서 거부한다.

안전장치: 리다이렉트를 따르지 않는다(SSRF 방지 — 호스트 검사는 호출자가 한다),
모든 응답이 요청한 구간과 정확히 같은 206 인지 확인하고 요청 크기 이상은 읽지 않는다,
블록 캐시는 LRU 로 상한을 둔다.
"""
from __future__ import annotations

import io
import re
import urllib.error
import urllib.request
from collections import OrderedDict

DEFAULT_BLOCK = 1 << 16
DEFAULT_CACHE_BLOCKS = 64
CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+|\*)")


class RangeNotSupported(IOError):
    pass


class RedirectRefused(IOError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RedirectRefused(f"redirect ({code}) refused")


_OPENER = urllib.request.build_opener(_NoRedirect)


class HttpRangeFile(io.RawIOBase):
    def __init__(self, url: str, block_size: int = DEFAULT_BLOCK, timeout: float = 30.0,
                 headers: dict[str, str] | None = None, cache_blocks: int = DEFAULT_CACHE_BLOCKS):
        self.url = url
        self.block_size = block_size
        self.timeout = timeout
        self.headers = dict(headers or {})
        self.cache_blocks = cache_blocks
        self.requests = 0
        self.bytes_fetched = 0
        self._pos = 0
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self.size = self._probe_size()

    def _range(self, start: int, end: int) -> tuple[bytes, int]:
        """[start, end] 구간을 읽고 (data, total_size) 를 반환한다. 206 + 일치하는 Content-Range 만 허용."""
        req = urllib.request.Request(self.url, headers={**self.headers, "Range": f"bytes={start}-{end}"})
        self.requests += 1
        try:
            resp = _OPENER.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            raise IOError(f"HTTP {exc.code} for range {start}-{end}") from None
        with resp:
            match = CONTENT_RANGE.fullmatch(resp.headers.get("Content-Range", "").strip())
            if resp.status != 206 or not match:
                raise RangeNotSupported(f"origin ignored Range (status {resp.status})")
            got_start, got_end, total = int(match[1]), int(match[2]), match[3]
            if got_start != start or got_end > end or total == "*":
                raise RangeNotSupported(f"origin returned range {got_start}-{got_end}/{total} for {start}-{end}")
            expected = got_end - got_start + 1
            data = resp.read(expected + 1)
        if len(data) != expected:
            raise IOError(f"range {start}-{end}: expected {expected} bytes, got {len(data)}")
        return data, int(total)

    def _probe_size(self) -> int:
        _, total = self._range(0, 0)
        return total

    def _block(self, index: int) -> bytes:
        if index in self._cache:
            self._cache.move_to_end(index)
            return self._cache[index]
        start = index * self.block_size
        end = min(start + self.block_size, self.size) - 1
        data, _ = self._range(start, end)
        if len(data) != end - start + 1:
            raise IOError(f"short range read {start}-{end}: got {len(data)} bytes")
        self.bytes_fetched += len(data)
        self._cache[index] = data
        if len(self._cache) > self.cache_blocks:
            self._cache.popitem(last=False)
        return data

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self.size}[whence]
        if base + offset < 0:
            raise ValueError("negative seek position")
        self._pos = base + offset
        return self._pos

    def readinto(self, buffer) -> int:
        view = memoryview(buffer).cast("B")
        remaining = min(len(view), max(self.size - self._pos, 0))
        written = 0
        while written < remaining:
            index, within = divmod(self._pos, self.block_size)
            chunk = self._block(index)[within:within + remaining - written]
            view[written:written + len(chunk)] = chunk
            written += len(chunk)
            self._pos += len(chunk)
        return written
