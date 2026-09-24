一个挂载网盘为 WebDAV 的轻量级工具，基于Python WsgiDAV开发，默认支持阿里云盘，可扩展其他网盘。

支持添加多网盘账户，支持配置文件加密，快速配置WebDav用户，SSL证书，服务端口。

## 安装与使用

安装DriveDAV：

```
git clone https://github.com/honwebx/drivedav.git
cd drivedav
pipx install ./
```

卸载：

```
pipx uninstall drivedav
```

配置网盘：

```
drivedav config
```

服务类命令：

```
drivedav start | stop | restart | status
```

WebDAV地址：

```
http://127.0.0.1:8080/[name]
```

配置文件加密后，可设置全局变量免除每次启动需要输入密码：

```
DRIVEDAV_CONFIG_PASS = "Password"
```

## 网盘接口开发

DriveDAV易扩展，如需支持其他网盘，实现DriveBackend网盘后端接口即可。

### 网盘接口：

在drives下创建网盘目录，例如：alipan

\_\_init\_\_.py中导出接口，名称必须为：Backend，并定义NAME常量。示例：

```
from .backend import AlipanBackend as Backend

NAME = "阿里云盘"
__all__ = ["Backend"]
```

DriveBackend抽象类：

```
from ...core.drive_backend import DriveBackend
```

DriveBackend中的抽象方法必须实现，可参考alipan/backend.py的实现。

| 方法        | 描述                                                         |
| ----------- | ------------------------------------------------------------ |
| config      | 网盘的配置过程，例如：OAuth授权获取Token。获取API所需的信息后，以字典数据返回，系统自动保存到配置文件。<br />注意：当is_new参数为True时，是用户新增网盘过程，DriveConfig中没有配置数据；is_new参数为False时，可使用DriveConfig读取旧配置信息。 |
| get_meta    | 获取资源元数据，包括目录和文件，成功返回字典数据，资源不存在返回None。<br />数据结构如下：<br />- name：资源名称，字符串值或None；<br />- size：文件大小，目录可不需要，单位：字节；<br />- created：资源创建时间的Unix timestamp；<br />- modified：资源最后修改时间的Unix timestamp；<br />- etag：文件的SHA，没有返回None；<br />- mime：文件的MIME类型；<br />- is_dir：是否为目录，布尔值：True \| False。 |
| list_dir    | 获取目录下子项名称列表：[name, name2...]                     |
| make_dir    | 创建目录，不用考虑多级，系统会自动处理多级的情况。           |
| read_file   | 读取文件流，返回requests的有效响应，requests请求时使用参数stream=True。<br />接收 headers 字典参数（可能包含 Range，用于分片下载）。 |
| open_writer | 上传文件，实现DriveUploadHandle抽象类，返回上传对象。<br />- write：客户端上传的文件流通过该方法写入；<br />- close：文件流写入完成时调用。 |
| delete      | 删除资源                                                     |
| move        | 移动/重命名资源                                              |
| copy        | 复制资源                                                     |

### 分片下载：

后端可声明类属性 `supports_ranges = True` 开启 206 分片响应（需 `read_file` 返回可 seek 流）。默认 `False`，Range 头仍透传给后端但对外只回 200。

```
class MyBackend(DriveBackend):
    supports_ranges = True
```

### 可用工具：

配置文件管理：DriveBackend类注入了配置文件管理工具。

```
def __init__(self, drive_config: "DriveConfig")

self._drive_config = drive_config

# 加载当前网盘所有配置项
self._cfg = self._drive_config.load()

# 保存当前网盘所有配置项
self._drive_config.save(self._cfg)
```

缓存：适当缓存API请求结果可减少API请求次数。

```
from ...utils.cache import Cache

......

self._cache = Cache(max_size=10000, default_ttl=600)

self._cache.set(key, value, ttl=900)
self._cache.get(key)
self._cache.delete(key)
```

节流器：API请求通常有QPS限制，阿里云盘为180毫秒，超过限制常返回429错误。节流器默认0.2秒间隔，可自行配置适合的间隔时间。

```
from ...utils.throttle import Throttler

# 至少0.2秒后执行
throttler = Throttler(min_interval=0.2)
throttler.wait()
```

一个包装请求方法的示例，使用了节流器：

```
self._session = requests.Session()
self._throttler = Throttler(min_interval=0.2)
......

def _request(self, method, url, **kwargs)-> dict[str, Any]:
    self._throttler.wait()

    access_token = ""
    headers = kwargs.pop("headers", {}) or {}
    headers["Content-Type"] = "application/json"
    headers["Authorization"] = f"Bearer {access_token}"

    try:
        resp = self._session.request(method, url, headers=headers, **kwargs)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise AlipanError.parse_response(getattr(e, "response", None), e)

    return resp.json()
```

错误处理：将网盘API错误转换为系统错误。

```
from ...core.drive_error import *

# 资源不存在时返回FileNotFound错误
raise FileNotFound("NotFound.File", "文件不存在...", "响应ID")
```

| 错误类             | 描述                                  |
| ------------------ | ------------------------------------- |
| FileNotFound       | 资源不存在，常见状态码：404           |
| TokenExpired       | Token过期，常见状态码：401            |
| RateLimitExceeded  | API限制，常见状态码：429              |
| PermissionDenied   | 请求被拒绝，常见状态码：403           |
| RangeNotSatisfiable| 请求范围无效，常见状态码：416         |
| ServiceUnavailable | 服务不可用，常见状态码：500、502、503 |
| DriveError         | 其他错误                              |

时间戳转换：将ISO8601和数字时间格式转换为 UTC 秒级时间戳。

```
from ...utils.helpers import to_utc_timestamp

modified_str = file_meta.get("updated_at")
modified = to_utc_timestamp(modified_str)
```

获取文件SHA1 哈希值：

```
from ...utils.helpers import sha1_file

content_hash = sha1_file(local_path)
```

获取文件前1K SHA1 哈希值：

```
from ...utils.helpers import sha1_file

pre_hash = sha1_head(local_path, head_size=1024)
```
