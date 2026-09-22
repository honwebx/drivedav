import sys
import os
import time
import tempfile
import signal
from wsgidav.wsgidav_app import WsgiDAVApp
from cheroot import wsgi
from ..config.wsgidav import wsgi_config

PID_FILE = os.path.join(tempfile.gettempdir(), "drivedav.pid")

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
    
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    run()

def stop_server():
    """
    停止DriveDAV服务器
    """

    if not os.path.exists(PID_FILE):
        print("DriveDAV 没有运行")
        return

    with open(PID_FILE) as f:
        pid = int(f.read())

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"正在关闭 DriveDAV...")
        expires_at = time.time() + 3
        while True:
            if not check_server_status():
                break

            if time.time() >= expires_at:
                os.kill(pid, signal.SIGKILL)
                break
        
            time.sleep(0.1)

        print(f"已停止 DriveDAV (PID {pid})")
    except ProcessLookupError:
        print("进程不存在")
    finally:
        if not check_server_status() and os.path.exists(PID_FILE):
            os.remove(PID_FILE)

def status_server():
    """
    输出DriveDAV服务器状态
    """

    if not os.path.exists(PID_FILE):
        print("DriveDAV 没有运行")
        return

    try:
        with open(PID_FILE) as f:
            pid = int(f.read())
    except (OSError, ValueError):
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

    if not os.path.exists(PID_FILE):
        return False

    try:
        with open(PID_FILE) as f:
            pid = int(f.read())
    except (OSError, ValueError):
        return False

    try:
        os.kill(pid, 0)
        return True
    except:
        return False
