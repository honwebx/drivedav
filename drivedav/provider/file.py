from typing import BinaryIO
from wsgidav.dav_provider import DAVNonCollection
from .resource import DriveDAVResource
from .error import error_to_dav
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

    def support_ranges(self) -> bool:
        """
        是否支持分片下载
        后端声明 supports_ranges=True（且 read_file 返回 可 seek 流）才开启，
        此时 WsgiDAV 回 206 + Content-Range
        未声明的后端保持 False
        """

        return bool(getattr(self._drive, "supports_ranges", False))

    def support_ranges(self) -> bool:
        """
        是否支持分片下载
        """

        return False

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

        self._upload_handle = self._drive.open_writer(self._path, file_size)
        return self._upload_handle

    def end_write(self, with_errors):
        """
        上传结束
        """

        if not self._upload_handle:
            return

        self._upload_handle.close()
        self._upload_handle = None
