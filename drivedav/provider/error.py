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
