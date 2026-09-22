from abc import ABC, abstractmethod
from typing import Any
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..config.drive import DriveConfig
    from .drive_upload_handle import DriveUploadHandle

class DriveBackend(ABC):
    """
    网盘后端抽象接口
    """

    def __init__(self, drive_config: "DriveConfig"):
        self._drive_config = drive_config

    @abstractmethod
    def config(self, is_new: bool = False) -> dict[str, Any]:
        """
        返回网盘配置
        """

    @abstractmethod
    def get_meta(self, path: str) -> dict[str, Any] | None:
        """
        返回文件或目录的元信息，例如：
        {
            "name": str,
            "size": int,
            "created": float,   # Unix timestamp
            "modified": float,   # Unix timestamp
            "etag": str | None,
            "mime": str,
            "is_dir": bool,
        }
        """

        pass

    @abstractmethod
    def list_dir(self, path: str) -> list:
        """
        返回目录下的名称列表
        """

        pass

    @abstractmethod
    def make_dir(self, path):
        """
        创建目录
        """

        pass

    @abstractmethod
    def read_file(self, path: str, headers: dict[str, str] = None):
        """
        返回文件内容 Response 对象
        """

        pass

    @abstractmethod
    def open_writer(self, dst_path: str, file_size: int = None) -> "DriveUploadHandle":
        """
        上传文件，返回一个可写的文件对象
        dst_path: 目标路径
        file_size: 文件大小
        返回DriveUploadHandle对象
        """

        pass

    @abstractmethod
    def delete(self, path: str):
        """
        删除文件
        """

        pass

    @abstractmethod
    def move(self, src_path: str, dst_path: str):
        """
        移动/重命名
        src_path: 源路径
        dst_path: 目标路径
        """

        pass

    @abstractmethod
    def copy(self, src_path: str, dst_path: str):
        """
        复制
        src_path: 源路径
        dst_path: 目标路径
        """
        
        pass
    