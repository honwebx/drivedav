from typing import BinaryIO
from wsgidav.dav_provider import DAVNonCollection
from .resource import DriveDAVResource
from .error import error_to_dav, DavUploadHandle
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from wsgidav.dav_provider import DAVProvider

class DriveDAVFile(DriveDAVResource, DAVNonCollection):
    """
    资源(文件)实现
    """

    def __init__(self, path: str, provider: "DAVProvider", environ: dict[str, Any]):
        super().__init__(path, provider, environ)
        DAVNonCollection.__init__(self, path, environ)
        self._stream = None
        self._upload_handle = None

    def support_content_length(self) -> bool:
        """
        是否支持Content-Length
        """

        return True

    def support_etag(self) -> bool:
        """
        是否支持ETag
        """

        return True

    def support_ranges(self) -> bool:
        """
        是否支持分片下载
        按后端 opt-in：后端声明 supports_ranges=True（且 read_file 返回
        可 seek 流）才开启，此时 WsgiDAV 回 206 + Content-Range；
        未声明的后端保持 False（旧行为：Range 透传 CDN 但对外只发 200）。
        """

        return bool(getattr(self._drive, "supports_ranges", False))

    def get_content_length(self) -> int | None:
        """
        返回文件大小（字节数）
        """

        meta = self._get_meta()
        return meta.get("size")

    def get_content_type(self) -> str | None:
        """
        返回 MIME 类型
        """

        meta = self._get_meta()
        return meta.get("mime")

    def get_etag(self) -> str | None:
        """
        返回 ETag
        """
        
        meta = self._get_meta()
        return meta.get("etag")

    def get_content(self) -> BinaryIO:
        """
        返回文件内容流
        """

        if self._stream:
            return self._stream
        
        headers = {}
        if "HTTP_RANGE" in self._environ:
            headers["Range"] = self._environ["HTTP_RANGE"]

        try:
            resp = self._drive.read_file(self._path, headers)
        except Exception as e:
            raise error_to_dav(e)

        resp.raw.decode_content = True
        self._stream = resp.raw
        return self._stream

    def begin_write(self, content_type=None):
        """
        创建上传对象
        """
        if self._upload_handle:
            return self._upload_handle

        content_length = self._environ.get("CONTENT_LENGTH")
        file_size = int(content_length) if content_length else None

        try:
            self._upload_handle = DavUploadHandle(
                self._drive.open_writer(self._path, file_size)
            )
        except Exception as e:
            raise error_to_dav(e)
        return self._upload_handle

    def end_write(self, with_errors):
        """
        上传结束
        with_errors=True 表示传输中途出错（wsgidav do_PUT except 路径）：
        调 handle.abort() 取消服务端残留上传，不做 complete/finalize，
        避免把 0 字节文件 finalize 成正式文件。
        """

        if not self._upload_handle:
            return

        if with_errors:
            try:
                abort = getattr(self._upload_handle, "abort", None)
                if callable(abort):
                    abort()
                else:
                    self._upload_handle.close()
            finally:
                self._upload_handle = None
                self._invalidate_meta(self._path)
            return

        try:
            self._upload_handle.close()
        finally:
            self._upload_handle = None
            self._invalidate_meta(self._path)