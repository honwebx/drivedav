import os
from platformdirs import user_config_dir

# 配置文件路径
CONFIG_FILE = user_config_dir("DriveDAV", "drivedav") + "/drivedav.conf"
# 配置文件密码
CONFIG_PASSWORD = os.getenv("DRIVEDAV_CONFIG_PASS")
# 日志级别：0-5，数字越大日志越详细，0为关闭日志
LOG_LEVEL = 0