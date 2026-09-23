from wsgidav.dav_error import DAVError

from ..core.drive_error import *

def map_error_to_http_status(err: DriveError):
    """
    将 DriveError 映射到 HTTP 状态码
    """

    if isinstance(err, FileNotFound):
        return 404
    if isinstance(err, PermissionDenied):
        return 403
    if isinstance(err, TokenExpired):
        return 401
    if isinstance(err, RateLimitExceeded):
        return 429
    if isinstance(err, RangeNotSatisfiable):
        return 416
    if isinstance(err, ServiceUnavailable):
        return 503
    
    return 500

def error_to_dav(err: Exception):
    """
    将 Error 转换为 DAVError
    """

    if isinstance(err, DAVError):
        return err

    if isinstance(err, DriveError):
        status = map_error_to_http_status(err)
        return DAVError(status, context_info=str(err))

    return DAVError(500, context_info=str(err))


class DavUploadHandle:
    """包装上传句柄，把 write/close 的异常统一转成 DAVError。

    wsgidav do_PUT 在 begin_write() 返回后直接调 handle.write(chunk)，
    不经过 provider 的 try 块；此包装确保 write/close 抛出的 DriveError
    能映射到正确 HTTP 状态码（如 TokenExpired→401），而非被包成 500。
    """

    __slots__ = ("_handle",)

    def __init__(self, handle):
        self._handle = handle

    def write(self, data):
        try:
            return self._handle.write(data)
        except Exception as e:
            raise error_to_dav(e)

    def close(self):
        try:
            return self._handle.close()
        except Exception as e:
            raise error_to_dav(e)

    def __getattr__(self, name):
        return getattr(self._handle, name)
