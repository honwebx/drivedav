import math
import time
import requests
from typing import Callable, Optional
from ...core.drive_upload_handle import DriveUploadHandle
from .error import AlipanError

_CHUNK_SIZE = 4 * 1024 * 1024
_UPLOAD_URL_TTL = 1800
_URL_PREFETCH = 5
_MAX_RETRIES = 3
_RETRY_BACKOFF = (0.5, 1.0, 2.0)
_PUT_TIMEOUT = (15, 120)


class AlipanUploadHandle(DriveUploadHandle):

    def __init__(
        self,
        api,
        parent_file_id: str,
        file_name: str,
        file_size: Optional[int] = None,
        finalize: Optional[Callable[[str, Optional[dict]], None]] = None,
    ):
        self._api = api
        self._file_size = file_size
        self._finalize = finalize
        self._oss_session = requests.Session()

        part_info_list = None
        if file_size:
            num_parts = math.ceil(file_size / _CHUNK_SIZE)
            part_info_list = [{"part_number": i} for i in range(1, num_parts + 1)]

        create_resp = self._api.create_source(
            parent_file_id=parent_file_id,
            name=file_name,
            size=file_size,
            part_info_list=part_info_list,
            check_name_mode="auto_rename",
        )
        self._file_id = create_resp["file_id"]
        self._upload_id = create_resp.get("upload_id")
        self._exist = bool(create_resp.get("exist", False))
        
        self._active = bool(self._upload_id) and not self._exist

        self._part_urls: dict[int, str] = {}
        self._urls_created_at = 0.0
        self._cache_part_urls(create_resp.get("part_info_list") or [])

        self._part_number = 1
        self._buffer = bytearray()
        self._failed = False

    def _cache_part_urls(self, parts):
        for part in parts:
            self._part_urls[part["part_number"]] = part["upload_url"]
        if parts:
            self._urls_created_at = time.time()

    def _get_part_url(self, part_number: int) -> str:
        """
        获取分片上传地址。
        命中且未过期则直接复用；否则批量预取 [_URL_PREFETCH] 个分片 URL，
        减少限流 API（getUploadUrl）的调用次数。
        """

        if part_number in self._part_urls and time.time() - self._urls_created_at < _UPLOAD_URL_TTL:
            return self._part_urls.pop(part_number)

        start = part_number
        end = part_number + _URL_PREFETCH
        if self._file_size:
            total = math.ceil(self._file_size / _CHUNK_SIZE)
            end = min(end, total + 1)

        resp = self._api.get_upload_url(
            file_id=self._file_id,
            upload_id=self._upload_id,
            part_numbers=list(range(start, end)),
        )
        self._cache_part_urls(resp.get("part_info_list") or [])

        if part_number not in self._part_urls:
            raise AlipanError.convert(400, "UploadUrlUnavailable", f"无法获取分片 {part_number} 的上传 URL")
        return self._part_urls.pop(part_number)

    def _upload_part(self, part_number: int, data: bytes):
        """
        上传分片。
        对可重试错误（网络错误、5xx、408、429、403[预签名 URL 过期可经
        getUploadUrl 恢复]）按指数退避重试 [_MAX_RETRIES] 次，
        仍失败才标记失败并抛出；其他 4xx 立即放弃。
        """

        last_err = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                upload_url = self._get_part_url(part_number)
                resp = self._oss_session.put(upload_url, data=data, timeout=_PUT_TIMEOUT)
                resp.raise_for_status()
                return
            except requests.RequestException as e:
                last_err = e
                status = getattr(getattr(e, "response", None), "status_code", None)
                retriable = status is None or status >= 500 or status in (408, 429, 403)
                if not retriable or attempt >= _MAX_RETRIES:
                    break
                if status == 403:
                    # 预签名 URL 过期：丢弃该分片缓存 URL，重试时强制重取
                    self._part_urls.pop(part_number, None)
                time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])
            except Exception:
                self._failed = True
                raise

        self._failed = True
        raise AlipanError.parse_response(getattr(last_err, "response", None), last_err) from last_err

    def write(self, data: bytes):
        """
        写入数据到缓冲区，当缓冲区达到 [_CHUNK_SIZE] 时自动上传分片。
        用偏移量批量消费，避免每次 del 前缀的 O(n²) memmove 开销。
        """

        if not self._active or self._failed:
            return

        self._buffer.extend(data)

        offset = 0
        while len(self._buffer) - offset >= _CHUNK_SIZE:
            chunk = bytes(self._buffer[offset:offset + _CHUNK_SIZE])
            offset += _CHUNK_SIZE
            self._upload_part(self._part_number, chunk)
            self._part_number += 1
        if offset:
            del self._buffer[:offset]

    def close(self):
        """
        完成上传：上传剩余分片、合并文件、执行 finalize 回调（替换旧文件）。
        只要创建了新文件就执行 finalize（秒传命中也一样，见内联注释），
        不依赖 _active；任何异常均标记失败并抛出，finally 保证本地资源清理。
        """

        if self._failed:
            self._cleanup()
            return

        try:
            complete_meta = None
            if self._active:
                if self._buffer:
                    self._upload_part(self._part_number, bytes(self._buffer))
                # complete 返回值是服务端权威的落盘 meta（含正确 size）：
                # 透传给 finalize 做缓存回填，让上传后立即的 rclone 校验读
                # 走缓存而非回源，绕开阿里云 complete 后的读后写延迟窗口。
                complete_meta = self._api.complete_upload(self._file_id, self._upload_id)
            # 只要创建了新文件就执行 finalize，不论是否秒传命中（_exist）：
            # 秒传同样产生了带 auto_rename 名的新文件，必须 trash 旧文件 +
            # rename 回原名，否则旧文件残留、新文件挂错名成为孤儿。
            if self._finalize:
                self._finalize(self._file_id, complete_meta)
        except Exception:
            self._failed = True
            raise
        finally:
            self._cleanup()

    def abort(self):
        """
        放弃上传：标记失败并取消服务端上传会话，不做 complete/finalize。
        对应 wsgidav do_PUT 抛错后调 end_write(with_errors=True) 的路径，
        避免把 0 字节残留文件 finalize 成正式文件。
        """

        self._failed = True
        self._cleanup()

    def _cleanup(self):
        """
        清理本地资源（缓冲区、OSS 连接）。
        上传失败且已创建服务端上传会话时，尝试 cancel 残留上传
        （失败不抛，仅尽力清理，避免阻塞本地资源释放）。
        """

        try:
            if self._failed and self._active and self._upload_id:
                self._api.cancel_upload(self._file_id, self._upload_id)
        except Exception:
            pass

        self._buffer.clear()
        self._oss_session.close()
