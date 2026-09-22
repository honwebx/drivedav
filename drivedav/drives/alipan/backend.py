import os
import requests
import time
from getpass import getpass
from ...utils.cache import Cache
from ...utils.helpers import to_utc_timestamp
from ...core.drive_backend import DriveBackend
from .error import AlipanError, FileNotFound
from .oauth import AlipanOAuth
from .api import AlipanAPI
from .upload_handle import AlipanUploadHandle
from typing import TypeVar, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...config.drive import DriveConfig

T = TypeVar("T")

class AlipanBackend(DriveBackend):
    """
    阿里云盘后端
    """

    def __init__(self, drive_config: "DriveConfig"):
        self._cache = Cache()
        self._drive_config = drive_config
        self._cfg = self._drive_config.load()
        self._api = AlipanAPI(self._cfg.get("drive_id"), self._refresh_token)
        self._oauth = AlipanOAuth(self._cfg.get("app_id"), self._cfg.get("app_secret"))
    
    @staticmethod
    def _parse_meta(file_meta: dict[str, Any]) -> dict[str, Any]:
        """
        解析文件元数据
        """

        created_str = file_meta.get("created_at")
        created = to_utc_timestamp(created_str)
        modified_str = file_meta.get("updated_at")
        modified = to_utc_timestamp(modified_str)

        if file_meta.get("type") == "folder":
            mime = "httpd/unix-directory"
        else:
            mime = file_meta.get("mime_type")
        
        return {
            "name": file_meta.get("name"),
            "size": file_meta.get("size"),
            "created": created,
            "modified": modified,
            "etag": file_meta.get("content_hash"),
            "mime": mime,
            "is_dir": file_meta.get("type") == "folder",
        }

    def _refresh_token(self) -> str:
        """
        获取访问令牌。
        如果令牌过期，自动刷新令牌。
        """

        if time.time() <= float(self._cfg.get("expires_at")) - 60:
            return self._cfg.get("access_token")
        
        access_token = self._oauth.refresh_token(self._cfg.get("refresh_token"))
        token_info = self._oauth.get_token_info()
        self._cfg.update(token_info)
        self._drive_config.save(self._cfg)
        
        return access_token

    def config(self, is_new: bool = False) -> dict[str, Any]:
        """
        返回网盘配置
        """

        if is_new:
            app_id = getpass("请输入阿里云盘 App ID: ").strip()
            app_secret = getpass("请输入阿里云盘 App Secret: ").strip()
        else:
            app_id = getpass(f"请输入阿里云盘 App ID(回车不修改: {self._cfg.get('app_id')}): ").strip()
            app_id = app_id if app_id else self._cfg.get("app_id")
            app_secret = getpass(f"请输入阿里云盘 App Secret(回车不修改: {self._cfg.get('app_secret')}): ").strip()
            app_secret = app_secret if app_secret else self._cfg.get("app_secret")
      
        oauth = AlipanOAuth(app_id, app_secret)

        print("\n请访问以下 URL 登录并授权：\n")
        print(oauth.get_authorize_url())
        code = input("\n授权完成后，请输入浏览器跳转 URL 中的 code: ").strip()

        oauth.exchange_code_for_token(code)
        oauth.get_drive_id()
        
        print("\n配置完成")

        return oauth.get_token_info()

    def get_meta(self, path: str) -> dict[str, Any] | None:
        """
        返回资源元信息
        """
        
        path = path.rstrip("/") or "/"
        if file_meta := self._cache.get(path):
            return file_meta

        try:
            file_meta = self._api.get_by_path(path)
        except FileNotFound as e:
            return None

        file_meta = AlipanBackend._parse_meta(file_meta)
        self._cache.set(path, file_meta)

        return file_meta

    def list_dir(self, path: str) -> list:
        """
        返回目录下的名称列表
        """

        path = path.rstrip("/") or "/"
        if lst := self._cache.get(f"lst_{path}"):
            return lst

        file_id = self._api.get_file_id(path)
        lst = self._api.list_files(file_id)
        names = []
        for item in lst:
            name = item.get("name")
            names.append(name)

            if not path.endswith("/"):
                child_path = path + "/" + name
            else:
                child_path = path + name

            child_meta = AlipanBackend._parse_meta(item)
            self._cache.set(child_path, child_meta)

        self._cache.set(f"lst_{path}", names)

        return names

    def make_dir(self, path: str):
        """
        创建目录
        """

        path = path.rstrip("/") or "/"
        parent_path = os.path.dirname(path) or "/"
        parent_file_id = self._api.get_file_id(parent_path)
        name = os.path.basename(path)
        result  = self._api.create_source(parent_file_id, name=name, type="folder")

        self._cache.delete(f"lst_{parent_path}")
        return result.get("file_id")

    def read_file(self, path: str, headers: dict[str, str] = None) -> requests.Response:
        """
        读取文件
        """

        path = path.rstrip("/") or "/"
        
        url = self._cache.get(f"dl_{path}")
        if not url:
            file_id = self._api.get_file_id(path)
            url = self._api.get_download_url(file_id, headers)
            self._cache.set(f"dl_{path}", url, 600)
        
        try:
            resp = requests.get(url, stream=True)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise AlipanError.parse_response(getattr(e, "response", None), e)
        
        return resp

    def open_writer(self, dst_path: str, file_size: int = None) -> AlipanUploadHandle:
        """
        上传文件到阿里云盘
        返回 AlipanUploadHandle 对象
        """

        dst_path = dst_path.rstrip("/") or "/"
        file_name = os.path.basename(dst_path)
        dst_parent_path = os.path.dirname(dst_path) or "/"

        try:
            dst_path_id = self._api.get_file_id(dst_path)
            self._api.trash(dst_path_id)
        except FileNotFound:
            pass
        
        dst_parent_file_id = self._api.get_file_id(dst_parent_path)
        upload_handle = AlipanUploadHandle(self._api, dst_parent_file_id, file_name, file_size)
        self._cache.delete(dst_path)
        self._cache.delete(f"lst_{dst_parent_path}")

        return upload_handle

    def delete(self, path: str):
        """
        删除资源，只放入回收站
        """

        path = path.rstrip("/") or "/"
        file_id = self._api.get_file_id(path)
        result = self._api.trash(file_id)
        async_task_id = result.get("async_task_id")
        self._wait_async_task(async_task_id)

        parent_path = os.path.dirname(path) or "/"
        self._cache.delete(path)
        self._cache.delete(f"lst_{parent_path}")

    def move(self, src_path: str, dst_path: str):
        """
        移动资源
        """
       
        src_path = src_path.rstrip("/") or "/"
        parent_path = os.path.dirname(src_path) or "/"
        dst_path = dst_path.rstrip("/") or "/"
        dst_parent_path = os.path.dirname(dst_path) or "/"
        dst_name = os.path.basename(dst_path)
        src_file_id = self._api.get_file_id(src_path)
        dst_parent_file_id = self._api.get_file_id(dst_parent_path)
        
        result = self._api.move(
            file_id=src_file_id,
            to_parent_file_id=dst_parent_file_id,
            new_name=dst_name
        )

        async_task_id = result.get("async_task_id")
        self._wait_async_task(async_task_id)

        self._cache.delete(src_path)
        self._cache.delete(f"lst_{parent_path}")

        self._cache.delete(dst_path)
        self._cache.delete(f"lst_{dst_parent_path}")
   
    def copy(self, src_path: str, dst_path: str):
        """
        复制资源
        """

        src_path = src_path.rstrip("/") or "/"
        dst_path = dst_path.rstrip("/") or "/"
        dst_parent_path = os.path.dirname(dst_path) or "/"
        src_file_id = self._api.get_file_id(src_path)
        dst_parent_file_id = self._api.get_file_id(dst_parent_path)
        
        result = self._api.copy(
            file_id=src_file_id,
            to_parent_file_id=dst_parent_file_id,
        )

        async_task_id = result.get("async_task_id")
        self._wait_async_task(async_task_id)
        
        self._cache.delete(dst_path)
        self._cache.delete(f"lst_{dst_parent_path}")

    def _wait_async_task(self, async_task_id: str):
        """
        等待异步任务完成
        """

        if not async_task_id:
            return
        
        timeout = 60  # 最大等待 60 秒
        interval = 1  # 每次轮询间隔
        waited = 0

        while waited < timeout:
            time.sleep(interval)
            waited += interval

            async_task_status = self._api.async_task(async_task_id)
            if async_task_status:
                return
            
            
        raise AlipanError.convert(400, "AsyncTaskFailed", f"异步任务失败：[{async_task_id}] 超时： {timeout} 秒")
