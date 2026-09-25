import time
import requests
from urllib.parse import urlencode
from .error import AlipanError

# OAuth 端点超时（连接，读取）：直接裸 post 无超时会永久阻塞，
# refresh_token 走服务端热路径且持有 _token_lock，必须防挂住。
_OAUTH_TIMEOUT = (10, 30)

class AlipanOAuth():
    """
    - OAuth 授权流程
    - refresh_token 生命周期管理（90 天）
    """

    def __init__(self, app_id: str, app_secret: str):
        self._token_info = {
            "app_id": app_id,
            "app_secret": app_secret,
            "access_token": None,
            "expires_at": 0,
            "refresh_token": None,
            "refresh_token_expires_at": 0,
        }
        self._refresh_token_expiry = 90 * 24 * 3600  # 90 天
        self._api_url = "https://openapi.alipan.com"

    def get_authorize_url(self, redirect_uri: str = "https://127.0.0.1/callback") -> str:
        """
        获取 OAuth 授权 URL
        redirect_uri: 重定向 URI（可选）
        """

        params = {
            "client_id": self._token_info["app_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "user:base,file:all:read,file:all:write",
        }
        return self._api_url + "/oauth/authorize?" + urlencode(params)

    def exchange_code_for_token(self, code: str, redirect_uri: str = "https://127.0.0.1/callback") -> str:
        """
        交换授权码获取访问令牌
        code: 授权码
        redirect_uri: 重定向 URI（可选）
        """

        url = self._api_url + "/oauth/access_token"
        data = {
            "client_id": self._token_info["app_id"],
            "client_secret": self._token_info["app_secret"],
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }

        try:
            resp = requests.post(url, json=data, timeout=_OAUTH_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise AlipanError.parse_response(getattr(e, "response", None), e)

        j = resp.json()

        self._token_info["access_token"] = j["access_token"]
        self._token_info["expires_at"] = time.time() + j["expires_in"]
        self._token_info["refresh_token"] = j["refresh_token"]
        self._token_info["refresh_token_expires_at"] = time.time() + self._refresh_token_expiry

        return self._token_info["access_token"]

    def refresh_token(self, refresh_token: str) -> str:
        """
        刷新访问令牌
        refresh_token: 刷新令牌
        """

        url = self._api_url + "/oauth/access_token"
        data = {
            "client_id": self._token_info["app_id"],
            "client_secret": self._token_info["app_secret"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        try:
            resp = requests.post(url, json=data, timeout=_OAUTH_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise AlipanError.parse_response(getattr(e, "response", None), e)

        j = resp.json()

        old_refresh_token = self._token_info["refresh_token"]
        self._token_info["access_token"] = j["access_token"]
        self._token_info["expires_at"] = time.time() + j["expires_in"]
        self._token_info["refresh_token"] = j.get("refresh_token", self._token_info["refresh_token"])

        # refresh_token 发生变化 → 更新时间
        if self._token_info["refresh_token"] != old_refresh_token:
            self._token_info["refresh_token_expires_at"] = time.time() + self._refresh_token_expiry

        return self._token_info["access_token"]

    def get_drive_id(self) -> str:
        """
        获取备份盘 ID
        """

        url =  f"{self._api_url}/adrive/v1.0/user/getDriveInfo"

        access_token = self._token_info.get("access_token")
        
        headers = {}
        headers["Content-Type"] = "application/json"
        headers["Authorization"] = f"Bearer {access_token}"
        
        try:
            resp = requests.post(url, headers=headers, timeout=_OAUTH_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise AlipanError.parse_response(getattr(e, "response", None), e)

        j = resp.json()
        # 备份盘缺失时回退默认盘/资源盘（resource-drive-only 账号无 backup_drive_id）
        drive_id = (
            j.get("backup_drive_id")
            or j.get("default_drive_id")
            or j.get("resource_drive_id")
        )
        self._token_info["drive_id"] = drive_id
        
        return self._token_info["drive_id"]

    def get_token_info(self) -> dict:
        """
        获取当前令牌信息
        """
        
        return self._token_info
