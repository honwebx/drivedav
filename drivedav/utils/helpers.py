import re
import hashlib
import posixpath
import ipaddress
from urllib.parse import unquote
from datetime import datetime, timezone

def normalize_path(path: str) -> str:
    """
    规范化路径，保留尾部斜杠语义
    """

    has_trailing_slash = path.endswith("/")
    path = path.split("?", 1)[0].split("#", 1)[0]
    path = unquote(path)
    path = posixpath.normpath(path)

    if not path.startswith("/"):
        path = "/" + path

    if has_trailing_slash and path != "/":
        path = path + "/"

    return path

def is_invalid_path(path: str) -> bool:
    """
    路径检测
    """

    if not path:
        return True

    if not path.startswith("/"):
        return True

    if "\x00" in path:
        return True

    if path in (".", ".."):
        return True

    parts = path.split("/")
    if any(part == ".." for part in parts):
        return True

    if len(path) >= 3 and path[1].isalpha() and path[2] == ":":
        return True

    return False

def normalize_trailing_slash(path: str, is_dir: bool) -> str:
    """
    根据资源类型规范化尾斜杠：
    - 目录：确保以 / 结尾
    - 文件：确保不以 / 结尾
    """
    
    if is_dir:
        return path.rstrip("/") + "/"
    else:
        return path.rstrip("/")

def to_utc_timestamp(value) -> float | None:
    """
    将时间格式转换为 UTC 秒级时间戳
    返回 None 表示无效或空时间
    """

    if value in (None, "", "null", "None"):
        return None

    # ISO8601 字符串
    if isinstance(value, str):
        value = value.strip()
        if value in ("0000-00-00T00:00:00Z", "0001-01-01T00:00:00Z"):
            return None

        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",  # 带毫秒
            "%Y-%m-%dT%H:%M:%SZ",     # 不带毫秒
            "%Y-%m-%d %H:%M:%S",      # 普通格式
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(value, fmt)
                dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                pass

        return None

    # 数字类型
    if isinstance(value, (int, float)):
        # 毫秒级（13位）
        if value > 1e12:
            return value / 1000

        if value > 0:
            return float(value)

        return None

    return None

def sha1_file(path: str, chunk_size: int = 4 * 1024 * 1024) -> str:
    """
    计算文件的 SHA1 哈希值
    """

    sha1 = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha1.update(chunk)
    return sha1.hexdigest().upper()

def sha1_head(path: str, head_size: int = 1024) -> str:
    """
    计算文件前 head_size 字节的 SHA1 哈希值
    """
    
    sha1 = hashlib.sha1()
    with open(path, "rb") as f:
        sha1.update(f.read(head_size))
    return sha1.hexdigest().upper()

def has_invalid_chars(name: str) -> bool:
    """
    检查名称是否包含无效字符（非字母、数字、下划线和短横线）
    """

    return not re.fullmatch(r"[A-Za-z0-9_-]+", name)

def is_valid_host(host: str) -> bool:
    """
    检查主机名是否有效（IP 或域名）
    """

    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass

    if not host or len(host) > 253:
        return False

    if host == "localhost":
        return True

    domain_regex = r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})*(\.[A-Za-z]{2,})?$"
    return re.match(domain_regex, host) is not None

def is_valid_port(port: str) -> bool:
    """
    检查端口号是否有效（1-65535）
    """

    if not port.isdigit():
        return False
    p = int(port)
    return 1 <= p <= 65535
