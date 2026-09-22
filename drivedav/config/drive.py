from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import GlobalConfigManager


class DriveConfig:
    """
    Drive 配置文件管理
    """

    def __init__(self, global_manager: "GlobalConfigManager", drive_name: str):
        self._section = f"drive.{drive_name}"
        self._view = global_manager.section(self._section)

    def load(self) -> dict:
        """
        加载 Drive 配置
        """

        data = self._view.load()
        data.pop("type", None)

        return data

    def save(self, data: dict):
        """
        保存 Drive 配置
        """
        
        old = self._view.load()
        data.pop("type", None)
        if "type" in old:
            data["type"] = old["type"]
            
        return self._view.save(data)
