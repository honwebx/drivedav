import os
import tempfile
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
            return f.read()

    def _write_raw(self, text: str):
        """
        写入原始配置
        """

        directory = os.path.dirname(self._config_file)
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".drivedav.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._config_file)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    def is_encrypted(self) -> bool:
        """
        检查配置是否加密
        """

        text = self._read_raw()
        return text.strip().startswith(self._marker)

    def load_full(self) -> dict:
        """
        加载完整配置
        """

        raw = self._read_raw().strip()
        if not raw:
            return {}

        encrypted = raw.startswith(self._marker)
        if self._enable_encrypt or encrypted:
            if not encrypted:
                print("读取配置失败：文件未加密")
                return {}
            if self._crypto is None:
                print("读取配置失败：未提供解密密码")
                return {}
            raw = self._strip_marker(raw)
            try:
                raw = self._crypto.decrypt(raw)
            except (ValueError, TypeError) as e:
                print(f"读取配置失败：{e}")
                return {}

        try:
            return tomllib.loads(raw)
        except Exception as e:
            print(f"读取配置失败：配置文件损坏（{e}）")
            return {}

    def save_full(self, data: dict):
        """
        保存完整配置
        """

        text = tomli_w.dumps(data)
        if self._enable_encrypt:
            if self._crypto is None:
                raise ValueError("未提供加密密码，无法保存加密配置")
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
            if not isinstance(cur, dict):
                return {}
            cur = cur.get(k, {})
        return cur if isinstance(cur, dict) else {}

    def _set_nested(self, data: dict, value: dict):
        """
        设置嵌套字典中的值
        """

        cur = data
        for k in self._keys[:-1]:
            node = cur.setdefault(k, {})
            if not isinstance(node, dict):
                node = {}
                cur[k] = node
            cur = node

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
