import posixpath
from .error import error_to_dav
from ..core.drive_error import FileNotFound
from ..utils.helpers import normalize_path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from wsgidav.dav_provider import DAVProvider


class DriveDAVResource():
    """
    资源基类
    """

    def __init__(self, path: str, provider: "DAVProvider", environ: dict[str, Any]):
        self._provider = provider
        self._environ = environ
        self._path = path
        self._drive = provider._drive

    def _get_meta(self) -> dict:
        """
        获取 Meta
        """

        meta = self._environ.get("drivedav.meta", {}).get(self._path)
        if not meta:
            return {}

        return meta

    def _invalidate_meta(self, path: str):
        """
        清理失效资源元数据
        path: 资源路径
        """

        cache = self._environ.get("drivedav.meta")
        if not cache:
            return

        path = path.rstrip("/") or "/"

        # 清理自身
        cache.pop(path, None)
        cache.pop(path + "/", None)

        # 清理父目录
        parent = posixpath.dirname(path) or "/"
        cache.pop(parent, None)
        cache.pop(parent + "/", None)

    def is_collection(self) -> bool:
        """
        判断是否为目录
        """

        meta = self._get_meta()
        
        if not meta:
            return self._path.endswith("/")

        return meta.get("is_dir", False)
        
    def support_recursive_move(self, dest_path: str) -> bool:
        """
        是否自己实现递归移动
        """

        return False

    def support_recursive_delete(self) -> bool:
        """
        是否自己实现递归删除
        """

        return False

    def get_display_name(self) -> str | None:
        """
        返回资源名称
        """

        meta = self._get_meta()
        return meta.get("name")

    def get_creation_date(self) -> float | None:
        """
        返回创建 Unix 时间戳
        """

        meta = self._get_meta()
        return meta.get("created")

    def get_last_modified(self) -> float | None:
        """
        返回最后修改 Unix 时间戳
        """
        
        meta = self._get_meta()
        return meta.get("modified")

    def delete(self):
        """
        删除资源
        """

        try:
            self._drive.delete(self._path)
            self._invalidate_meta(self._path)
        except FileNotFound:
            self._invalidate_meta(self._path)
            return
        except Exception as e:
            raise error_to_dav(e)
        
    def copy_move_single(self, dest_path: str, *,  is_move: bool):
        """
        复制/移动资源
        dest_path: 目标路径
        is_move: True=移动, False=复制
        """
        
        dest_path = normalize_path(dest_path)

        if is_move:
            try:
                self._drive.move(self._path, dest_path)
                self._invalidate_meta(self._path)
                self._invalidate_meta(dest_path)
            except Exception as e:
                raise error_to_dav(e)
        else:
            try:
                self._drive.copy(self._path, dest_path)
                self._invalidate_meta(dest_path)
            except Exception as e:
                raise error_to_dav(e)
