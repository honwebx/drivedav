from wsgidav.dav_provider import DAVCollection
from wsgidav.dav_error import DAVError, HTTP_BAD_REQUEST
from .resource import DriveDAVResource
from .error import error_to_dav
from urllib.parse import unquote
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from wsgidav.dav_provider import DAVProvider

class DriveDAVCollection(DriveDAVResource, DAVCollection):
    """
    集合(目录)实现
    """
    
    def __init__(self, path: str, provider: "DAVProvider", environ: dict[str, Any]):
        super().__init__(path, provider, environ)
        DAVCollection.__init__(self, path, environ)

    def get_member_names(self) -> list:
        """
        获取集合成员名称列表
        """

        try:
            lst = self._drive.list_dir(self._path)
        except Exception as e:
            raise error_to_dav(e)

        return lst or []

    def get_member(self, name: str) -> DriveDAVResource | None:
        """
        根据名称获取成员
        name: 成员名称
        """

        if not name or "/" in name[:-1] or name in (".", ".."):
            return None
        base_path = self._path if self._path.endswith("/") else self._path + "/"
        child_path = base_path + name

        return self._provider.get_resource_inst(child_path, self._environ)

    def _ensure_parents(self, path):
        """
        确保路径所有父目录存在
        """

        path = unquote(path)
        parts = path.strip("/").split("/")
        cur = "/"

        for p in parts[:-1]:
            cur = cur.rstrip("/") + "/" + p + "/"
            if not self._provider.exists(cur, self._environ):
                self._drive.make_dir(cur)
                self._invalidate_meta(cur)

    def create_collection(self, name: str) -> DriveDAVResource:
        """
        创建集合
        name: 集合名称
        """

        if not name or "/" in name or name in (".", ".."):
            raise DAVError(HTTP_BAD_REQUEST)
        base_path = self._path if self._path.endswith("/") else self._path + "/"
        collection_path = base_path + name + "/"

        try:
            self._ensure_parents(collection_path)
            self._drive.make_dir(collection_path)
            self._invalidate_meta(collection_path)
        except Exception as e:
            raise error_to_dav(e)

        return self._provider.get_resource_inst(collection_path, self._environ)
    
    def create_empty_resource(self, name: str) -> DriveDAVResource:
        """
        创建空文件
        name: 文件名称
        """

        if not name or "/" in name or name in (".", ".."):
            raise DAVError(HTTP_BAD_REQUEST)
        base_path = self._path if self._path.endswith("/") else self._path + "/"
        file_path = base_path + name
        self._invalidate_meta(file_path)

        return self._provider.get_resource_inst(file_path, self._environ)
