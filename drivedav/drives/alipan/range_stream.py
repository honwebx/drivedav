"""
CDN 可 seek 流（包内私有）
"""

from __future__ import annotations

import time
from typing import Any, Callable

import requests
import urllib3

# CDN 单次请求超时（连接，读取）：读取无限会导致卡死 socket 永久阻塞 worker
_READ_TIMEOUT = (15, 60)

_CHUNK = 65536

# _open() 尝试次数 = 1 + len(_OPEN_BACKOFF)；每次重试前先睡对应秒数。
_OPEN_BACKOFF = (2, 5, 10)

# 流中途断开、重开续读前的固定退避（_open 内部退避另算）。
_RESUME_BACKOFF = 3


class _RetrySentinel:
    """
    刷链成功标记：_map_http_error 刷链后返回此单例，调用方继续读当前连接。
    """

    __slots__ = ()


_RETRY_SENTINEL = _RetrySentinel()


class RangeStream:
    """
    按需 Range 回源的可 seek 流。内存恒定，只缓冲当前块。
    """

    def __init__(
        self,
        url: str,
        session: requests.Session,
        headers: dict[str, str] | None = None,
        total_size: int | None = None,
        on_refresh_url: Callable[["RangeStream"], str] | None = None,
    ):
        self._url = url
        self._session = session
        # 401/403（CDN 直链过期）时刷直链：由 backend 注入，一次下载会话
        # 内最多触发一次（见 backend refreshed 守卫），无注入则直接抛错。
        self._on_refresh_url = on_refresh_url
        self._headers = dict(headers or {})
        # 初始 Range 由调用方解析后经 seek() 设定；此处不再解析，避免双重处理
        self._headers.pop("Range", None)
        self._headers.pop("range", None)
        try:
            self._total = int(total_size) if total_size is not None else None
        except (TypeError, ValueError):
            self._total = None
        self._pos = 0
        self._resp: requests.Response | None = None
        self.decode_content = True
        self._closed = False

    # ---------- 内部 ----------

    def _close_resp(self):
        if self._resp is not None:
            try:
                self._resp.close()
            except Exception:
                pass
            self._resp = None

    def _map_http_error(self, resp: requests.Response, exc: Exception):
        from ...core.drive_error import RangeNotSatisfiable

        status = getattr(resp, "status_code", 0) or 0
        if status == 416:
            # 不带签名 URL：str(exc) 含 CDN 直链查询串，泄露 OSS 签名
            return RangeNotSatisfiable("416", f"CDN Range 不满足（status=416, pos={self._pos}）", "")
        if status in (401, 403) and self._on_refresh_url is not None:
            # CDN 直链过期：刷一次直链后按当前位置重开，不消耗退避次数。
            # 刷链本身抛的错（含“已刷过仍 403”）直接上浮，不再包装。
            # _open_fresh 的连接错误（无 .response）由调用方重试路径处理。
            self._url = self._on_refresh_url(self)
            self._close_resp()
            self._open_fresh()
            assert self._resp is not None
            return _RETRY_SENTINEL
        from .error import AlipanError

        return AlipanError.parse_response(resp, exc)

    def _open(self):
        """
        按当前位置打开 CDN 连接；连接层错误退避重试后仍败抛 503。

        HTTP 错误（401/403/416/其他）直接经 _map_http_error 处理：
        401/403 且有刷链 hook 时内部已刷链重开、返回哨兵，调用方继续读。
        """
        from ...core.drive_error import ServiceUnavailable

        self._close_resp()
        headers = dict(self._headers)
        if self._pos > 0:
            headers["Range"] = f"bytes={self._pos}-"
        last_exc: Exception | None = None
        for attempt in range(1 + len(_OPEN_BACKOFF)):
            if attempt:
                time.sleep(_OPEN_BACKOFF[attempt - 1])
            try:
                self._open_fresh(headers)
                return
            except (requests.RequestException, urllib3.exceptions.HTTPError) as e:
                if getattr(e, "response", None) is not None:
                    mapped = self._map_http_error(e.response, e)
                    if mapped is _RETRY_SENTINEL:
                        return
                    raise mapped from e
                last_exc = e
                # 连接层失败：先 close session 驱逐池中毒化的半死连接
                # （只清闲置池连接，不掐其他流正在传的连接），再退避重试。
                # 注意：_map_http_error 内部 _open_fresh 的连接错误也会落到
                # 这里（同一 except），重试继续按当前位置重开，无死循环。
                try:
                    self._session.close()
                except Exception:
                    pass
        # 错误消息不带 str(last_exc)：其 URL 部分含 OSS 签名查询串
        raise ServiceUnavailable(
            "CDNConnectFailed",
            f"CDN 建连失败，已退避重试 {len(_OPEN_BACKOFF)} 次"
            f"（{'/'.join(map(str, _OPEN_BACKOFF))}s）"
            "（rclone 会自动重试续传）",
            "",
        )

    def _open_fresh(self, headers: dict[str, str] | None = None):
        """单次 CDN 建连：成功则 self._resp 就绪；失败抛 requests 异常。"""
        if headers is None:
            headers = dict(self._headers)
            if self._pos > 0:
                headers["Range"] = f"bytes={self._pos}-"
        resp = self._session.get(
            self._url, headers=headers, stream=True, timeout=_READ_TIMEOUT
        )
        resp.raise_for_status()
        self._resp = resp
        if self._total is None:
            self._total = self._peek_total(resp)

    @staticmethod
    def _peek_total(resp: requests.Response) -> int | None:
        try:
            cr = resp.headers.get("Content-Range", "")
            if cr.startswith("bytes ") and "/" in cr:
                total = cr.rsplit("/", 1)[-1].strip()
                if total.isdigit():
                    return int(total)
            cl = resp.headers.get("Content-Length")
            if cl and str(cl).isdigit():
                return int(cl)
        except Exception:
            pass
        return None

    # ---------- 文件接口 ----------

    def read(self, n: int = -1) -> bytes:
        if self._closed:
            return b""
        if n is None or (isinstance(n, int) and n < 0):
            # 读到 EOF：循环收块，不断流重开一次续读
            # （n 为 None 视为读至 EOF，与 io.BytesIO.read(None) 语义一致）
            out = bytearray()
            while True:
                chunk = self._read_block(_CHUNK)
                if not chunk:
                    break
                out.extend(chunk)
            return bytes(out)
        if not n:
            return b""
        return self._read_block(n)

    def _read_block(self, n: int) -> bytes:
        from ...core.drive_error import ServiceUnavailable

        if self._resp is None:
            self._open()
        try:
            assert self._resp is not None
            data = self._resp.raw.read(n)
        except (requests.RequestException, urllib3.exceptions.HTTPError) as e:
            # raw.read 可抛 urllib3 底层异常（ProtocolError/IncompleteRead），
            # 同 requests 错误一并进重试/刷链路径。
            if getattr(e, "response", None) is not None:
                mapped = self._map_http_error(e.response, e)
                if mapped is not _RETRY_SENTINEL:
                    raise mapped
                # 401/403 已刷链重开：读当前新连接
                assert self._resp is not None
                data = self._resp.raw.read(n)
            else:
                # 流中途断开：退避后按当前位置重开一次续读
                # （_open 内部还有自己的退避序列；整形窗口下耐心比次数重要）
                time.sleep(_RESUME_BACKOFF)
                try:
                    self._open()
                    assert self._resp is not None
                    data = self._resp.raw.read(n)
                except (requests.RequestException, urllib3.exceptions.HTTPError) as e2:
                    if getattr(e2, "response", None) is not None:
                        mapped2 = self._map_http_error(e2.response, e2)
                        if mapped2 is not _RETRY_SENTINEL:
                            raise mapped2
                        assert self._resp is not None
                        data = self._resp.raw.read(n)
                    else:
                        raise ServiceUnavailable(
                            "CDNReadFailed",
                            f"CDN 读取中断，已重开续读仍失败（pos={self._pos}）", "",
                        )
        if not data:
            return b""
        self._pos += len(data)
        return data

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 1:
            self._pos += offset
        elif whence == 2:
            base = self._total if self._total is not None else 0
            self._pos = base + offset
        else:
            self._pos = offset
        if self._pos < 0:
            self._pos = 0
        # 位置变化即废弃当前连接，读时按新位置重开
        self._close_resp()
        return self._pos

    def tell(self) -> int:
        return self._pos

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def flush(self):
        return None

    def close(self):
        self._close_resp()
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def __iter__(self) -> Any:
        while True:
            chunk = self.read(_CHUNK)
            if not chunk:
                break
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *args: Any):
        self.close()
        return False
