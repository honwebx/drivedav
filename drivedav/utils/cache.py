import threading
import time
from collections import OrderedDict
from typing import Any, Optional

class Cache:
    """
    缓存类
    max_size: 最大缓存数量
    default_ttl: 默认缓存时间（秒）
    """

    def __init__(self, max_size: int = 10000, default_ttl: int = 600):
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            now = time.time()
            item = self._cache.get(key)

            if not item:
                return None

            expire_at, value = item
            if expire_at > now:
                self._cache.move_to_end(key)
                return value

            self._cache.pop(key, None)
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        with self._lock:
            ttl = ttl if ttl is not None else self._default_ttl
            expire_at = time.time() + ttl

            self._cache[key] = (expire_at, value)
            self._cache.move_to_end(key)

            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def delete(self, key: str):
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()
