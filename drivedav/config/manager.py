import os
import tomli_w
from typing import TYPE_CHECKING, Optional

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

if TYPE_CHECKING:
    from ..utils.crypto import Crypto

class GlobalConfigManager:
    def __init__(self, config_file: str, crypto: Optional["Crypto"] = None, enable_encrypt: bool = False):
        self._config_file = config_file
        self._crypto = crypto
        self._enable_encrypt = enable_encrypt
        self._marker = "DRIVEDAV_ENC:"

    def _strip_marker(self, text: str) -> str:
        """
        移除加密标记
        """
        
        return text[len(self._marker):]

    def _add_marker(self, text: str) -> str:
        """
        添加加密标记
        """
        
        return self._marker + text

    def _read_raw(self) -> str:
        """
        读取原始配置
        """

        if not os.path.exists(self._config_file):
            return ""
        with open(self._config_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _write_raw(self, text: str):
        """
        写入原始配置
        """

        os.makedirs(os.path.dirname(self._config_file), exist_ok=True)
        with open(self._config_file, "w", encoding="utf-8") as f:
            f.write(text)

    def is_encrypted(self) -> bool:
        """
        检查配置是否加密
        """

        text = self._read_raw()
        return text.startswith(self._marker)

    def load_full(self) -> dict:
        """
        加载完整配置
        """

        raw = self._read_raw()
        if not raw:
            return {}

        if self._enable_encrypt:
            raw = self._strip_marker(raw)
            try:
                raw = self._crypto.decrypt(raw)
            except ValueError as e:
                print(f"读取配置失败：{e}")
                return {}

        return tomllib.loads(raw)

    def save_full(self, data: dict):
        """
        保存完整配置
        """

        text = tomli_w.dumps(data)
        if self._enable_encrypt:
            text = self._crypto.encrypt(text)
            text = self._add_marker(text)
        
        self._write_raw(text)

    def section(self, name: str) -> "SectionConfig":
        """
        获取指定节的配置
        """

        return SectionConfig(self, name)

    def enable_encryption(self, enable: bool):
        """
        启用或禁用加密
        """

        self._enable_encrypt = enable

    def inject_crypto(self, crypto: Optional["Crypto"] = None):
        """
        注入 Crypto 实例
        """

        self._crypto = crypto


class SectionConfig:
    def __init__(self, manager: GlobalConfigManager, section: str):
        self._manager = manager
        self._keys = section.split(".")

    def _get_nested(self, data: dict):
        """
        获取嵌套字典中的值
        """

        cur = data
        for k in self._keys:
            cur = cur.get(k, {})
        return cur

    def _set_nested(self, data: dict, value: dict):
        """
        设置嵌套字典中的值
        """

        cur = data
        for k in self._keys[:-1]:
            cur = cur.setdefault(k, {})

        cur[self._keys[-1]] = value

    def _del_nested(self, data: dict):
        """
        删除嵌套字典中的指定键
        """

        cur = data
        stack = []

        for k in self._keys[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                return
            stack.append((cur, k))
            cur = cur[k]

        cur.pop(self._keys[-1], None)

        # 从下往上清理空字典
        while stack:
            parent, key = stack.pop()
            if not parent[key]:
                parent.pop(key)
            else:
                break


    def load(self) -> dict:
        """
        加载指定节的配置
        """

        data = self._manager.load_full()
        return self._get_nested(data)

    def save(self, value: dict):
        """
        保存指定节的配置
        """

        data = self._manager.load_full()
        self._set_nested(data, value)
        self._manager.save_full(data)

    def delete(self):
        data = self._manager.load_full()
        self._del_nested(data)
        self._manager.save_full(data)
