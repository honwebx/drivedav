import time
import threading

class Throttler:
    """
    节流器，限制API调用的最小间隔
    min_interval: 最小间隔时间，单位秒
    """
    def __init__(self, min_interval=0.2):
        self._min_interval = min_interval
        self._last_call_time = 0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.time()
            wait_time = self._last_call_time + self._min_interval - now
            if wait_time > 0:
                time.sleep(wait_time)
            self._last_call_time = time.time()