from wsgidav.dav_provider import DAVProvider
from wsgidav.dav_error import DAVError, HTTP_BAD_REQUEST

from .collection import DriveDAVCollection
from .file import DriveDAVFile
from .error import error_to_dav, FileNotFound
from ..utils.helpers import normalize_path, is_invalid_path, normalize_trailing_slash
from typing import Any

# from wsgidav import util
# _logger = util.get_module_logger(__name__)
# _logger.propagate = True

class DriveDAVProvider(DAVProvider):
    """
    DriveDAV 网盘提供者
    """

    def __init__(self, drive):
        super().__init__()
        self._drive = drive

    def _load_meta(self, path: str, environ: dict):
        """
        加载资源元数据
        path: 资源路径
        """

        cache = environ.setdefault("drivedav.meta", {})

        if path in cache:
            return cache[path]
            
        try:
            meta = self._drive.get_meta(path)
            # _logger.debug(f"加载元数据：{path} -> {meta}")
        except FileNotFound as e:
            cache[path] = None
            return None
        except Exception as e:
            raise error_to_dav(e)

        if not meta:
            cache[path] = None
            return None
            
        path_normalize = normalize_trailing_slash(path, meta.get("is_dir"))
        cache[path_normalize] = meta
        if path_normalize != path:
            cache[path] = meta

        return meta

    def exists(self, path, environ):
        """
        判断资源是否存在
        """

        path = normalize_path(path)
        
        if is_invalid_path(path):
            raise DAVError(HTTP_BAD_REQUEST)
            
        meta = self._load_meta(path, environ)

        return bool(meta)

    def get_resource_inst(self, path: str, environ: dict[str, Any]) -> DriveDAVCollection | DriveDAVFile | None:
        """
        根据路径获取资源实例
        path: 资源路径
        environ: WSGI环境字典
        """

        path = normalize_path(path)

        if is_invalid_path(path):
            return None

        meta = self._load_meta(path, environ)
        if meta:
            path = normalize_trailing_slash(path, meta.get("is_dir"))

        if path.endswith("/"):
            return DriveDAVCollection(path, self, environ)
       
        return DriveDAVFile(path, self, environ)
