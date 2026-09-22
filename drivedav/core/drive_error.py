class DriveError(Exception):
    """
    网盘错误处理基类
    """
    
    def __init__(self, code: str, message: str, request_id: str = ""):
        super().__init__(f"[{code}] {message} (req: {request_id})")
        self._code = code
        self._message = message
        self._request_id = request_id

    @property
    def code(self) -> str:
        return self._code

    @property
    def message(self) -> str:
        return self._message

    @property
    def request_id(self) -> str:
        return self._request_id


class FileNotFound(DriveError): pass
class TokenExpired(DriveError): pass
class RateLimitExceeded(DriveError): pass
class PermissionDenied(DriveError): pass
class ServiceUnavailable(DriveError): pass
