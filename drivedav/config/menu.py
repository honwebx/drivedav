from .manager import GlobalConfigManager
from .drive import DriveConfig
from ..env import CONFIG_FILE, CONFIG_PASSWORD
from ..core.drive_error import DriveError
from ..core.server import check_server_status
from ..utils.crypto import Crypto
from ..utils.helpers import has_invalid_chars, is_valid_port, is_valid_host
from tabulate import tabulate
from getpass import getpass
from pathlib import Path
import importlib

def config_main():
    """
    配置主菜单
    """
    
    if check_server_status():
        print("配置前需要先停止服务，使用命令：drivedav stop")
        return

    cfg_manager = GlobalConfigManager(CONFIG_FILE)

    if cfg_manager.is_encrypted():
        if not CONFIG_PASSWORD:
            config_pass = getpass("请输入配置文件密码: ")
            cfg_manager.inject_crypto(Crypto(config_pass))
        else:
            cfg_manager.inject_crypto(Crypto(CONFIG_PASSWORD))

        cfg_manager.enable_encryption(True)

    try:
        while True:
            show_drive(cfg_manager)

            choice = input(
                "\ne) 编辑网盘    n) 添加网盘  d) 删除网盘\n"
                "u) 用户管理    s) 证书配置  o) 系统设置\n"
                "c) 配置加密    q) 退出 \n"
                "> "
            ).strip().lower()

            if choice == "e":
                edit_drive(cfg_manager)
            elif choice == "n":
                new_drive(cfg_manager)
            elif choice == "d":
                delete_drive(cfg_manager)
            elif choice == "u":
                manage_users(cfg_manager)
            elif choice == "s":
                ssl_cert(cfg_manager)
            elif choice == "o":
                server_setting(cfg_manager)
            elif choice == "c":
                config_password(cfg_manager)
            elif choice == "q":
                return
            else:
                print("无效选项，请重新输入。")
    except KeyboardInterrupt:
        print("\n已退出配置菜单")

def show_drive(cfg_manager: GlobalConfigManager):
    """
    列出所有网盘
    """

    all_drives = cfg_manager.section("drive").load()

    if not all_drives:
        return

    rows = []
    for name, item in all_drives.items():
        drive_type = item.get("type")
        if not drive_type: continue
        try:
            module = importlib.import_module(f"..drives.{drive_type}", package=__package__)
            rows.append([name, getattr(module, "NAME", drive_type)])
        except ModuleNotFoundError:
            pass

    if not rows:
        return

    print("\n已配置的网盘：")
    print(tabulate(
        rows,
        tablefmt="simple",
    ))

def new_drive(cfg_manager: GlobalConfigManager):
    """
    创建新的网盘配置
    """

    drives_dir = Path(__file__).parent.parent / "drives"
    drive_types = sorted(
        p.name for p in drives_dir.iterdir()
        if p.is_dir() and p.name != "__pycache__"
    )

    if not drive_types:
        print("没有可用的网盘")
        return

    for idx, d in enumerate(drive_types, start=1):
        try:
            module = importlib.import_module(f"..drives.{d}", package=__package__)
            print(f"{idx:>2}) {getattr(module, 'NAME', d)}")
        except ModuleNotFoundError:
            pass

    # 选择网盘类型
    while True:
        choice = input("输入数字选择网盘 > ").strip()
        if not choice.isdigit():
            print("请输入数字。")
            continue

        choice = int(choice)
        if 1 <= choice <= len(drive_types):
            drive_type = drive_types[choice - 1]
            break
        else:
            print("无效输入，请输入数字。")

    # 输入名称
    all_drives = cfg_manager.section("drive").load()

    while True:
        name = input("请输入名称: ").strip()

        if not name:
            print("名称不能为空")
            continue

        if has_invalid_chars(name):
            print("名称只能包含英文、数字、短横线和下划线，请重新输入。")
            continue

        if name in all_drives:
            print("名称已存在，请重新输入。")
            continue

        break

    module = importlib.import_module(f"..drives.{drive_type}", package=__package__)
    drive_config = DriveConfig(cfg_manager, name)
    backend = module.Backend(drive_config)
    
    try:
        config = backend.config(is_new=True)
    except DriveError as e:
        print(f"配置失败：{e.message}")
        return
        
    config["type"] = drive_type

    cfg_manager.section(f"drive.{name}").save(config)

def edit_drive(cfg_manager: GlobalConfigManager):
    """
    编辑已有的网盘配置
    """

    all_drives = cfg_manager.section("drive").load()

    if not all_drives:
        print("当前没有任何网盘配置")
        return

    drive_names = sorted(all_drives.keys())

    # 列出所有 drive
    rows = []
    for idx, name in enumerate(drive_names, start=1):
        drive_type = all_drives[name].get("type", "unknown")
        try:
            module = importlib.import_module(f"..drives.{drive_type}", package=__package__)
            rows.append([idx, name, getattr(module, "NAME", drive_type)])
        except ModuleNotFoundError:
            pass

    print("已配置的网盘：")
    print(tabulate(
        rows,
        colalign=["right", "left", "left"],
        tablefmt="simple",
    ))

    # 选择要编辑的 drive
    while True:
        choice = input("输入数字选择要编辑的网盘 > ").strip()
        if not choice.isdigit():
            print("请输入数字")
            continue

        choice = int(choice)
        if 1 <= choice <= len(drive_names):
            name = drive_names[choice - 1]
            break
        else:
            print("无效输入，请重新输入")

    # 加载旧配置
    section = cfg_manager.section(f"drive.{name}")
    old_config = section.load()

    drive_type = old_config.get("type")
    if not drive_type:
        print("配置损坏：缺少网盘类型")
        return

    # 加载 backend
    module = importlib.import_module(f"..drives.{drive_type}", package=__package__)
    drive_config = DriveConfig(cfg_manager, name)
    backend = module.Backend(drive_config)
    
    try:
        new_config = backend.config(is_new=False)
    except DriveError as e:
        print(f"配置失败：{e.message}")
        return

    drive_config.save(new_config)

def delete_drive(cfg_manager: GlobalConfigManager):
    """
    删除网盘
    """

    all_drives = cfg_manager.section("drive").load()

    if not all_drives:
        print("当前没有任何网盘配置")
        return

    drive_names = sorted(all_drives.keys())

    rows = []
    for idx, name in enumerate(drive_names, start=1):
        drive_type = all_drives[name].get("type", "unknown")
        try:
            module = importlib.import_module(f"..drives.{drive_type}", package=__package__)
            rows.append([idx, name, getattr(module, "NAME", drive_type)])
        except ModuleNotFoundError:
            pass
    
    print("已配置的网盘：")
    print(tabulate(
        rows,
        colalign=["right", "left", "left"],
        tablefmt="simple",
    ))

    while True:
        choice = input("输入数字选择要删除的网盘 > ").strip()
        if not choice.isdigit():
            print("请输入数字")
            continue

        choice = int(choice)
        if 1 <= choice <= len(drive_names):
            name = drive_names[choice - 1]
            break
        else:
            print("无效输入，请重新输入")

    # 二次确认
    confirm = input(f"确认删除网盘 '{name}'? (Y/n) > ").strip().lower()
    if confirm != "y":
        print("已取消删除")
        return

    # 删除配置
    cfg_manager.section(f"drive.{name}").delete()

    print(f"已删除网盘配置：{name}")

def manage_users(cfg_manager: GlobalConfigManager):
    """
    管理 WebDAV 用户：添加 / 编辑 / 删除
    """

    while True:
        print("\n用户管理：")
        print("1) 添加用户")
        print("2) 修改密码")
        print("3) 删除用户")
        print("4) 返回上级菜单")

        choice = input("> ").strip()

        if choice == "1":
            add_user(cfg_manager)
        elif choice == "2":
            edit_user(cfg_manager)
        elif choice == "3":
            delete_user(cfg_manager)
        elif choice == "4":
            return
        else:
            print("无效输入，请重新选择")

def add_user(cfg_manager: GlobalConfigManager):
    """
    添加用户
    """

    section = cfg_manager.section("dav.user")
    user = section.load()

    if user:
        print("用户已存在，无法添加")
        return

    username = input("输入用户名 > ").strip()
    if not username:
        print("用户名不能为空")
        return

    password = input("输入密码 > ").strip()
    if not password:
        print("密码不能为空")
        return

    section.save({
        "username": username,
        "password": password,
    })

    print(f"已添加用户：{username}")

def edit_user(cfg_manager: GlobalConfigManager):
    """
    编辑用户
    """

    section = cfg_manager.section("dav.user")
    user = section.load()

    if not user:
        print("当前没有用户，请先添加")
        return

    print(f"当前用户：{user.get('username')}")

    new_password = input("输入新密码（留空则不修改） > ").strip()
    if new_password:
        user["password"] = new_password
        section.save(user)
        print("密码已更新")
    else:
        print("未修改密码")

def delete_user(cfg_manager: GlobalConfigManager):
    """
    删除用户
    """

    section = cfg_manager.section("dav.user")
    user = section.load()

    if not user:
        print("当前没有用户")
        return

    confirm = input(f"确认删除用户 '{user.get('username')}'? (Y/n) > ").strip().lower()
    if confirm != "y":
        print("已取消删除")
        return

    cfg_manager.section("dav.user").delete()
    print("用户已删除")

def config_password(cfg_manager: GlobalConfigManager):
    """
    配置文件密码
    """

    while True:
        print("\n配置文件密码管理：")
        print("1. 设置密码")
        print("2. 删除密码")
        print("3. 返回上级菜单")

        choice = input("> ").strip()

        if choice == "1":
            set_config_password(cfg_manager)
        elif choice == "2":
            delete_config_password(cfg_manager)
        elif choice == "3":
            return
        else:
            print("无效输入，请重新选择")

def set_config_password(cfg_manager: GlobalConfigManager):
    """
    设置配置文件密码
    """
 
    p1 = getpass("输入密码 > ").strip()
    p2 = getpass("再次输入密码 > ").strip()

    if p1 != p2:
        print("两次输入不一致，设置失败")
        return

    if not p1:
        print("密码不能为空")
        return

    cfg = cfg_manager.load_full()
    cfg_manager.inject_crypto(Crypto(p1))
    cfg_manager.enable_encryption(True)
    cfg_manager.save_full(cfg)

    print("密码已设置，配置文件已加密。密码不会保存在任何地方，请记住你的密码，遗忘会导致配置文件不可用。")

def delete_config_password(cfg_manager: GlobalConfigManager):
    """
    删除配置文件密码
    """

    if not cfg_manager.is_encrypted():
        print("当前没有设置配置文件密码")
        return

    confirm = input("确认删除密码？(Y/n) > ").strip().lower()
    if confirm != "y":
        print("已取消删除")
        return

    cfg = cfg_manager.load_full()
    cfg_manager.inject_crypto(crypto=None)
    cfg_manager.enable_encryption(False)
    cfg_manager.save_full(cfg)

    print("密码已删除，配置文件已解密")

def ssl_cert(cfg_manager: GlobalConfigManager):
    """
    配置 SSL 证书
    """

    while True:
        print("\nSSL 证书：")
        print("1) 配置证书")
        print("2) 删除证书配置")
        print("3) 返回上级菜单")

        choice = input("> ").strip()

        if choice == "1":
            configure_ssl_cert(cfg_manager)
            return
        elif choice == "2":
            delete_ssl_cert(cfg_manager)
            return
        elif choice == "3":
            return
        else:
            print("无效输入，请重新选择")

def configure_ssl_cert(cfg_manager: GlobalConfigManager):
    """
    SSL 证书配置
    """

    section = cfg_manager.section("dav.ssl")
    ssl_conf = section.load() or {}

    old_cert = ssl_conf.get("ssl_certificate")
    old_key = ssl_conf.get("ssl_private_key")

    if old_cert or old_key:
        print(f"当前证书：{old_cert}")
        print(f"当前私钥：{old_key}")
        print("留空则不修改")

    cert = input("输入 SSL 证书路径 > ").strip()
    key = input("输入 SSL 私钥路径 > ").strip()

    if cert:
        ssl_conf["ssl_certificate"] = cert
    elif not old_cert:
        print("证书路径不能为空")
        return

    if key:
        ssl_conf["ssl_private_key"] = key
    elif not old_key:
        print("私钥路径不能为空")
        return

    section.save(ssl_conf)

    if old_cert or old_key:
        print("SSL 证书配置已更新")
    else:
        print("SSL 证书已设置")

def delete_ssl_cert(cfg_manager: GlobalConfigManager):
    """
    删除 SSL 证书配置
    """

    section = cfg_manager.section("dav.ssl")
    ssl_conf = section.load()

    if not ssl_conf:
        print("当前没有 SSL 证书配置")
        return

    confirm = input("确认删除 SSL 证书配置？(Y/n) > ").strip().lower()
    if confirm != "y":
        print("已取消删除")
        return

    cfg_manager.section("dav.ssl").delete()
    print("SSL 证书配置已删除")

def server_setting(cfg_manager: GlobalConfigManager):
    """
    配置 WebDAV 服务器
    """

    section = cfg_manager.section("dav.server")
    server_conf = section.load() or {}

    old_host = server_conf.get("host")
    old_port = server_conf.get("port")

    if old_host or old_port:
        print(f"当前 host：{old_host}")
        print(f"当前 port：{old_port}")
        print("留空则不修改对应字段")

    host = input("输入 host（IP 或域名）> ").strip()
    if host:
        if not is_valid_host(host):
            print("无效的 host，请输入合法的 IP 或域名")
            return
        server_conf["host"] = host
    elif not old_host:
        print("host 不能为空")
        return

    port = input("输入 port（1-65535）> ").strip()
    if port:
        if not is_valid_port(port):
            print("无效的 port，请输入 1-65535")
            return
        server_conf["port"] = int(port)
    elif not old_port:
        print("port 不能为空")
        return

    section.save(server_conf)

    if old_host or old_port:
        print("服务器设置已更新")
    else:
        print("服务器设置已保存")
