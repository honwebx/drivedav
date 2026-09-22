import argparse
from .core.server import *
from .config.menu import config_main
from importlib.metadata import version, PackageNotFoundError


def main():
    parser = argparse.ArgumentParser(description="DriveDAV WebDAV Server")
    parser.add_argument(
        "command",
        choices=["start", "stop", "restart", "status", "config", "version"],
        help="可用命令: start | stop | restart | status | config | version"
    )

    args = parser.parse_args()

    if args.command == "start":
        start_server()
    elif args.command == "stop":
        stop_server()
    elif args.command == "restart":
        stop_server()
        start_server()
    elif args.command == "status":
        status_server()
    elif args.command == "config":
        config_main()
    elif args.command == "version":
        show_version()

def show_version():
    """
    显示DriveDAV版本
    """

    try:
        print(f"DriveDAV 版本 {version('drivedav')}")
    except PackageNotFoundError:
        print("DriveDAV 版本未知")
