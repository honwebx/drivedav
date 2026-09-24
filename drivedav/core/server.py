import sys
import os
import time
import tempfile
import signal
from wsgidav.wsgidav_app import WsgiDAVApp
from cheroot import wsgi
from ..config.wsgidav import wsgi_config

PID_FILE = os.path.join(tempfile.gettempdir(), "drivedav.pid")

def _write_pid_file():
    fd = os.open(PID_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode())
    finally:
        os.close(fd)

def _remove_pid_file():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass

def _read_pid():
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None

def run():
    config = wsgi_config()
    if not config:
        print("启动失败，配置不存在")
        return

    app = WsgiDAVApp(config)
    server = wsgi.Server(
        bind_addr=(config["host"], config["port"]),
        wsgi_app=app
    )

    try:
        server.start()
    except KeyboardInterrupt:
        print("用户中断，服务器已停止")
    except Exception as e:
        print(f"服务器启动失败: {e}")
        sys.exit(1)
    finally:
        server.stop()

def start_server():
    """
    启动DriveDAV服务器
    """

    if check_server_status():
        print("DriveDAV 已在运行")
        return

    try:
        _write_pid_file()
    except OSError as e:
        print(f"写入 PID 文件失败: {e}")
        return

    try:
        run()
    finally:
        _remove_pid_file()

def stop_server():
    """
    停止DriveDAV服务器
    """

    pid = _read_pid()
    if pid is None:
        _remove_pid_file()
        print("DriveDAV 没有运行")
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print("进程不存在")
        _remove_pid_file()
        return
    except OSError as e:
        print(f"停止失败：{e}")
        return

    print("正在关闭 DriveDAV...")
    expires_at = time.time() + 3
    force_killed = False
    while True:
        if not check_server_status():
            break
        if time.time() >= expires_at:
            if force_killed:
                break
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                break
            force_killed = True
            expires_at = time.time() + 2
        time.sleep(0.1)

    if check_server_status():
        print(f"停止失败，进程仍在运行 (PID {pid})")
        return

    _remove_pid_file()
    print(f"已停止 DriveDAV (PID {pid})")

def status_server():
    """
    输出DriveDAV服务器状态
    """

    pid = _read_pid()
    if pid is None:
        if not os.path.exists(PID_FILE):
            print("DriveDAV 没有运行")
        else:
            print("PID 文件损坏或无法读取")
        return

    try:
        os.kill(pid, 0)
        print(f"DriveDAV 正在运行 (PID {pid})")
    except ProcessLookupError:
        print("PID 文件存在但进程不存在")
    except OSError as e:
        print(f"无法确定进程状态：{e}")

def check_server_status():
    """
    检查DriveDAV服务器状态
    """

    pid = _read_pid()
    if pid is None:
        return False

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
