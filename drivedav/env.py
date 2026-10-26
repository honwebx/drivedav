import os
from platformdirs import user_config_dir

# 配置文件路径
CONFIG_FILE = user_config_dir("DriveDAV", "drivedav") + "/drivedav.conf"
# 配置文件密码
CONFIG_PASSWORD = os.getenv("DRIVEDAV_CONFIG_PASS")
# 日志文件路径（后台运行且开启日志时使用）
LOG_FILE = "/tmp/drivedav.log"