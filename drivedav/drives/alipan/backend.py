import posixpath
import re
import requests
import threading
import time
from getpass import getpass
from ...utils.cache import Cache
from ...utils.helpers import to_utc_timestamp
from ...core.drive_backend import DriveBackend
from .error import AlipanError, FileNotFound, PermissionDenied, ServiceUnavailable
from .oauth import AlipanOAuth
from .api import AlipanAPI
from .range_stream import RangeStream
from .upload_handle import AlipanUploadHandle
from typing import TypeVar, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...config.drive import DriveConfig

T = TypeVar("T")

class AlipanBackend(DriveBackend):
    """
    阿里云盘后端
    """

    # read_file 返回可 seek 的 RangeStream：声明支持分片下载
    supports_ranges = True

    def __init__(self, drive_config: "DriveConfig"):
        self._cache = Cache()
        self._drive_config = drive_config
        self._cfg = self._drive_config.load()
        # token 刷新临界区锁：多线程共享一个后端实例，check-then-refresh 必须串行，
        # 否则两个线程同时用旧 RT 刷新会被 Aliyun 轮换机制作废其中一个（间歇 401）。
        self._token_lock = threading.Lock()
        self._api = AlipanAPI(self._cfg.get("drive_id"), self._refresh_token)
        self._oauth = AlipanOAuth(self._cfg.get("app_id"), self._cfg.get("app_secret"))
        # 数据面 CDN 会话：复用 TLS 连接，与控制面 session（AlipanAPI 内）分离。
        self._dl_session = requests.Session()
    
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
            "file_id": file_meta.get("file_id"),
        }

    def _refresh_token(self) -> str:
        """
        获取访问令牌。
        如果令牌过期，自动刷新令牌。
        多线程并发时经 _token_lock 串行（双重检查），避免同时用旧 RT
        刷新被 Aliyun 轮换机制判定失效；save 失败不抛（内存已更新，
        当前会话不受影响，仅重启后需重新刷新）。
        """

        if time.time() <= float(self._cfg.get("expires_at", 0) or 0) - 60:
            return self._cfg.get("access_token")

        with self._token_lock:
            # 二次检查：另一线程可能已刷新
            if time.time() <= float(self._cfg.get("expires_at", 0) or 0) - 60:
                return self._cfg.get("access_token")

            access_token = self._oauth.refresh_token(self._cfg.get("refresh_token"))
            token_info = self._oauth.get_token_info()
            self._cfg.update(token_info)
            try:
                self._drive_config.save(self._cfg)
            except Exception as e:
                print(f"警告：令牌刷新成功但配置保存失败（重启后需重新刷新）：{e}")

            return access_token

    @staticmethod
    def _mask_secret(value: str | None) -> str:
        """
        密钥掩码显示：只露尾 4 位，屏幕不出现完整密钥。
        """

        value = (value or "").strip()
        if not value:
            return "（未设置）"
        return f"****{value[-4:]}"

    def config(self, is_new: bool = False) -> dict[str, Any]:
        """
        返回网盘配置
        """

        if is_new:
            app_id = ""
            while not app_id:
                app_id = getpass("请输入阿里云盘 App ID: ").strip()
                if not app_id:
                    print("App ID 不能为空，请重新输入")
            app_secret = ""
            while not app_secret:
                app_secret = getpass("请输入阿里云盘 App Secret: ").strip()
                if not app_secret:
                    print("App Secret 不能为空，请重新输入")
            keys_changed = True
        else:
            old_app_id = self._cfg.get("app_id", "") or ""
            old_app_secret = self._cfg.get("app_secret", "") or ""
            print(f"当前 App ID: {self._mask_secret(old_app_id)}")
            app_id = getpass("输入新的 App ID（留空保留）> ").strip() or old_app_id
            print(f"当前 App Secret: {self._mask_secret(old_app_secret)}")
            app_secret = getpass("输入新的 App Secret（留空保留）> ").strip() or old_app_secret
            keys_changed = (app_id != old_app_id) or (app_secret != old_app_secret)

        if keys_changed:
            # 密钥新建或已变更：旧令牌不再适用，必须重新授权。
            oauth = AlipanOAuth(app_id, app_secret)
            print("\n请访问以下 URL 登录并授权：\n")
            print(oauth.get_authorize_url())
            code = ""
            while not code:
                code = input("\n授权完成后，请输入浏览器跳转 URL 中的 code: ").strip()
                if not code:
                    print("code 不能为空（密钥已变更，必须重新授权），请重新输入")
            oauth.exchange_code_for_token(code)
            oauth.get_drive_id()
            print("\n授权完成")
            config = oauth.get_token_info()
        else:
            # 密钥未变更：code 可跳过，整套旧授权原样保留。
            print("\n如需重新授权，请访问以下 URL（code 留空则保留旧授权）：\n")
            print(AlipanOAuth(app_id, app_secret).get_authorize_url())
            code = input("\n请输入浏览器跳转 URL 中的 code（留空跳过）: ").strip()
            if code:
                oauth = AlipanOAuth(app_id, app_secret)
                oauth.exchange_code_for_token(code)
                oauth.get_drive_id()
                print("\n授权完成")
                config = oauth.get_token_info()
            else:
                print("已保留旧授权信息")
                config = dict(self._cfg)

        if not config.get("refresh_token"):
            print("警告：当前配置无有效授权令牌，后续使用可能失败，请重新授权")

        print("\n配置完成")
        return config

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
        parent_path = posixpath.dirname(path) or "/"
        parent_file_id = self._api.get_file_id(parent_path)
        name = posixpath.basename(path)
        result = self._api.create_source(parent_file_id, name=name, type="folder")

        self._cache.delete(f"lst_{parent_path}")
        return result.get("file_id")

    def _resolve_download_url(self, path: str) -> str:
        """
        取（或刷）path 的 CDN 直链：优先读 meta 缓存里的 file_id，
        未命中再 get_by_path，避免每次下载都打一次路径解析接口。
        """

        meta = self._cache.get(path)
        file_id = meta.get("file_id") if meta else None
        if not file_id:
            file_id = self._api.get_file_id(path)
        if not file_id:
            raise FileNotFound("NotFound.File", "文件不存在", "")
        return self._api.get_download_url(file_id)

    def _get_cached_download_url(self, path: str) -> str:
        """
        取（或刷）path 的 CDN 直链：dl_{path} 缓存 600s TTL
        （< STS 凭证 x-oss-expires=900s），缓存未命中时
        _resolve_download_url 重取。
        """

        path = path.rstrip("/") or "/"
        url = self._cache.get(f"dl_{path}")
        if url:
            return url
        url = self._resolve_download_url(path)
        self._cache.set(f"dl_{path}", url, 600)
        return url

    def read_file(self, path: str, headers: dict[str, str] = None) -> requests.Response:
        """
        读取文件
        返回可 seek 的 RangeStream（包在 Response 里）：WsgiDAV 在
        support_ranges=True 时经 seek/read 切片回 206，rclone/wget/aria2c
        可断点续传。CDN 直链过期（401/403）时由 RangeStream 经
        on_refresh_url 刷一次新链重开，刷过仍败直接抛（区分过期链与坏身份）。
        """

        path = path.rstrip("/") or "/"

        url = self._get_cached_download_url(path)

        if not url:
            raise AlipanError.convert(404, "NotFound.File", "无法获取下载链接", "")

        fwd_headers = dict(headers or {})

        # 初始 Range（如有）转为流起始位置；WsgiDAV 后续 seek 会覆盖它。
        start_pos = 0
        m = re.search(r"bytes=(\d+)-", fwd_headers.get("Range", ""))
        if m:
            try:
                start_pos = int(m.group(1))
            except ValueError:
                start_pos = 0

        total_size: int | None = None
        meta = self._cache.get(path)
        if meta:
            try:
                total_size = int(meta.get("size", 0)) or None
            except (TypeError, ValueError):
                total_size = None

        # 403-only 刷链：稳定态不碰控制面；CDN 直链过期时 RangeStream
        # 把 403 报上来，这里刷一次新链、换掉缓存和流内 URL。刷过仍 403
        # 直接抛，不循环刷——把"过期链"和"坏身份"两种失败严格分开。
        refreshed = {"done": False}

        def _refresh_url(stream: "RangeStream") -> str:
            if refreshed["done"]:
                raise PermissionDenied(
                    "CDNLinkStillInvalid",
                    "CDN 直链已刷过一次仍 403：非过期链，可能权限/身份问题", "",
                )
            refreshed["done"] = True
            new_url = self._resolve_download_url(path)
            if not new_url:
                raise AlipanError.convert(404, "NotFound.File", "无法获取下载链接", "")
            self._cache.set(f"dl_{path}", new_url, 600)
            return new_url

        stream = RangeStream(
            url, self._dl_session, fwd_headers, total_size, on_refresh_url=_refresh_url,
        )
        if start_pos:
            stream.seek(start_pos)
        resp = requests.Response()
        resp.status_code = 200
        # resp.url 不存签名直链（OSS Signature/凭证泄露），仅记逻辑路径
        resp.url = path
        resp.raw = stream  # type: ignore[attr-defined]
        return resp

    def open_writer(self, dst_path: str, file_size: int = None) -> AlipanUploadHandle:
        """
        上传文件到阿里云盘
        返回 AlipanUploadHandle 对象

        采用「先传后替换」的原子策略：以 auto_rename 创建新文件上传，
        上传成功后再删除旧文件并把新文件重命名回原文件名，避免上传失败
        时丢失旧文件。期间旧文件保持可读。
        """

        dst_path = dst_path.rstrip("/") or "/"
        file_name = posixpath.basename(dst_path)
        dst_parent_path = posixpath.dirname(dst_path) or "/"

        old_file_id = None
        try:
            old_file_id = self._api.get_file_id(dst_path)
        except FileNotFound:
            pass

        dst_parent_file_id = self._api.get_file_id(dst_parent_path)
        upload_handle = AlipanUploadHandle(
            self._api,
            dst_parent_file_id,
            file_name,
            file_size,
            finalize=lambda new_id: self._finalize_upload(
                new_id, old_file_id, file_name, dst_path, dst_parent_path
            ),
        )

        return upload_handle

    def _finalize_upload(self, new_file_id, old_file_id, file_name, dst_path, parent_path):
        """
        上传成功后替换旧文件：删除旧文件 → 等待异步任务 → 重命名新文件回原名 → 失效缓存。
        无旧文件时跳过删除与重命名，仅失效缓存。
        """

        if old_file_id:
            result = self._api.trash(old_file_id)
            async_task_id = result.get("async_task_id")
            if async_task_id:
                self._wait_async_task(async_task_id)
            self._api.rename(new_file_id, file_name)

        self._cache.delete(dst_path)
        self._cache.delete(f"dl_{dst_path}")
        self._cache.delete(f"lst_{parent_path}")

    def delete(self, path: str):
        """
        删除资源，只放入回收站
        """

        path = path.rstrip("/") or "/"
        file_id = self._api.get_file_id(path)
        result = self._api.trash(file_id)
        async_task_id = result.get("async_task_id")
        self._wait_async_task(async_task_id)

        parent_path = posixpath.dirname(path) or "/"
        self._cache.delete(path)
        self._cache.delete(f"dl_{path}")
        self._cache.delete(f"lst_{parent_path}")

    def move(self, src_path: str, dst_path: str):
        """
        移动资源
        """
       
        src_path = src_path.rstrip("/") or "/"
        parent_path = posixpath.dirname(src_path) or "/"
        dst_path = dst_path.rstrip("/") or "/"
        dst_parent_path = posixpath.dirname(dst_path) or "/"
        dst_name = posixpath.basename(dst_path)
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
        self._cache.delete(f"dl_{src_path}")
        self._cache.delete(f"lst_{parent_path}")

        self._cache.delete(dst_path)
        self._cache.delete(f"lst_{dst_parent_path}")
   
    def copy(self, src_path: str, dst_path: str):
        """
        复制资源
        """

        src_path = src_path.rstrip("/") or "/"
        dst_path = dst_path.rstrip("/") or "/"
        dst_parent_path = posixpath.dirname(dst_path) or "/"
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
        先查一次（同步完成时不白等），未完成再轮询；大文件复制/移动
        可能较慢，超时放宽到 120s；超时按 503（任务可能仍在跑），而非 400。
        """

        if not async_task_id:
            return

        timeout = 120  # 最大等待 120 秒
        interval = 1  # 每次轮询间隔
        waited = 0

        while True:
            if self._api.async_task(async_task_id):
                return
            if waited >= timeout:
                break
            time.sleep(interval)
            waited += interval

        raise ServiceUnavailable(
            "AsyncTaskTimeout",
            f"异步任务超时：[{async_task_id}] {timeout} 秒（任务仍可能在服务端继续执行）", "",
        )
