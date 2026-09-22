from ...core.drive_error import *


class AlipanError:
    """
    将阿里云盘 API 错误转换为 DriveError
    """

    CODE_MAP = {
        # 400
        "QRCodeExpired": DriveError,
        "QuotaExhausted.Drive": DriveError,
        "NotFound.File": FileNotFound,
        "NotFound.FileId": FileNotFound,

        # 401
        "AccessTokenExpired": TokenExpired,
        "AccessTokenInvalid": TokenExpired,
        "RefreshTokenExpired": TokenExpired,
        "RefreshTokenInvalid": TokenExpired,

        # 403
        "PermissionDenied": PermissionDenied,
        "ForbiddenFileInTheRecycleBin": PermissionDenied,
        "ExceedCapacityForbidden": PermissionDenied,
        "UserNotAllowedAccessDrive": PermissionDenied,
        
        # 429
        "TooManyRequests": RateLimitExceeded,
    }

    # HTTP 状态码 → 默认错误类型
    STATUS_MAP = {
        400: DriveError,
        401: TokenExpired,
        403: PermissionDenied,
        404: FileNotFound,
        429: RateLimitExceeded,
        500: ServiceUnavailable,
        502: ServiceUnavailable,
        503: ServiceUnavailable,
    }

    @classmethod
    def convert(cls, status: int, code: str, message: str, request_id: str = ""):
        """
        根据 HTTP 状态码、错误码、错误信息生成对应的 DriveError
        status: HTTP 状态码
        code: 错误码
        message: 错误信息
        request_id: 请求 ID（可选）
        """

        if code in cls.CODE_MAP:
            err_cls = cls.CODE_MAP[code]
            return err_cls(code, message, request_id)

        if status in cls.STATUS_MAP:
            err_cls = cls.STATUS_MAP[status]
            return err_cls(code, message, request_id)

        return DriveError(code, message, request_id)

    @classmethod
    def parse_response(cls, resp, exc):
        """
        解析阿里云盘 API 返回值
        resp: requests.Response 对象
        exc: 异常对象
        """
        
        status = getattr(resp, "status_code", None)

        try:
            data = resp.json() if resp is not None else {}
        except Exception:
            data = {}

        code = data.get("code", "UnknownError")
        message = data.get("message", str(exc))
        request_id = (
            data.get("requestId")
            or data.get("request_id")
            or resp.headers.get("x-ca-request-id")
            or "" )

        return cls.convert(status, code, message, request_id)


