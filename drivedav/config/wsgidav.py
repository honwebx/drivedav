import os
import importlib
from wsgidav.http_authenticator import HTTPAuthenticator
from wsgidav.request_resolver import RequestResolver
from ..provider import DriveDAVProvider, XmlErrorPrinter
from ..env import CONFIG_FILE, CONFIG_PASSWORD, LOG_LEVEL
from .manager import GlobalConfigManager
from .drive import DriveConfig
from ..utils.crypto import Crypto
from getpass import getpass


def wsgi_config():
    """
    创建WSGI配置
    """

    if not os.path.exists(CONFIG_FILE):
        return None
    
    global_manager = GlobalConfigManager(CONFIG_FILE)
    if global_manager.is_encrypted():
        if not CONFIG_PASSWORD:
            config_pass = getpass("请输入配置文件密码: ")
            global_manager.inject_crypto(Crypto(config_pass))
        else:
            global_manager.inject_crypto(Crypto(CONFIG_PASSWORD))
        
        global_manager.enable_encryption(True)

    global_cfg = global_manager.load_full()

    if not global_cfg:
        return None

    wsgi_cfg = {
        "server": "cheroot",
        "host": "127.0.0.1",
        "port": 8080,
        "provider_mapping": {},
        "http_authenticator": {
            "domain_controller": None,
            "accept_basic": True,
            "accept_digest": True,
            "default_to_digest": True,
        },
        "simple_dc": {
            "user_mapping": {
                "*": True,
            }
        },
        "middleware_stack": [
            XmlErrorPrinter,
            HTTPAuthenticator,
            RequestResolver,
        ],
        # "numthreads": 1,
        "verbose": LOG_LEVEL, # 日志级别：0-5
    }

    all_drives = global_cfg.get("drive", {})
    if all_drives:
        for name, item in all_drives.items():
            drive_type = item.get("type") if isinstance(item, dict) else None
            if not drive_type:
                print(f"跳过网盘 '{name}'：配置缺少类型")
                continue
            try:
                module = importlib.import_module(f"..drives.{drive_type}", package=__package__)
            except ModuleNotFoundError:
                print(f"跳过网盘 '{name}'：类型不可用 '{drive_type}'")
                continue
            drive_config = DriveConfig(global_manager, name)
            provider = DriveDAVProvider(module.Backend(drive_config))
            wsgi_cfg["provider_mapping"][f"/{name}"] = provider
    else:
        return None

    if not wsgi_cfg["provider_mapping"]:
        return None

    dav_cfg = global_cfg.get("dav", {})
    if not isinstance(dav_cfg, dict):
        dav_cfg = {}
    dav_server = dav_cfg.get("server")
    if not isinstance(dav_server, dict):
        dav_server = {}
    if dav_server:
        if dav_server.get("host"):
            wsgi_cfg["host"] = dav_server["host"]
        if dav_server.get("port"):
            wsgi_cfg["port"] = dav_server["port"]

    dav_user = dav_cfg.get("user")
    if dav_user:
        wsgi_cfg["simple_dc"]["user_mapping"]["*"] = {
            dav_user.get("username"): {
                "password": dav_user.get("password"),
            }
        }
    else:
        print("警告：未配置 WebDAV 用户，匿名可访问服务")

    dav_ssl = dav_cfg.get("ssl")
    if dav_ssl:
        wsgi_cfg["ssl_certificate"] = dav_ssl.get("ssl_certificate")
        wsgi_cfg["ssl_private_key"] = dav_ssl.get("ssl_private_key")

    return wsgi_cfg

