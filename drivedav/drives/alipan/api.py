import requests
from typing import Any
from ...utils.throttle import Throttler
from .error import AlipanError

class AlipanAPI:
    """
    阿里云盘 API 封装
    """

    def __init__(self, drive_id: str, refresh_token: callable):
        self._api_url = "https://openapi.alipan.com"
        self._drive_id = drive_id
        self._refresh_token = refresh_token
        self._session = requests.Session()
        self._throttler = Throttler()
    
    @staticmethod
    def _filter_data(data: dict[str]) -> dict:
        """
        过滤资源数据字段，只保留指定的字段
        """

        fields = {"file_id", "parent_file_id", "name", "type", "size", "file_extension", "mime_type", "content_hash", "created_at", "updated_at"}

        return {k: data.get(k) for k in fields if k in data}

    def _request(self, method, url, **kwargs)-> dict[str, Any]:
        self._throttler.wait()

        access_token = self._refresh_token()
        headers = kwargs.pop("headers", {}) or {}
        headers["Content-Type"] = "application/json"
        headers["Authorization"] = f"Bearer {access_token}"
        
        try:
            resp = self._session.request(method, url, headers=headers, **kwargs)
            if resp.status_code == 400:
                if "PreHashMatched" == resp.json().get("code"):
                    return resp.json()

            resp.raise_for_status()
        except requests.RequestException as e:
            raise AlipanError.parse_response(getattr(e, "response", None), e)

        return resp.json()

    def list_files(self, parent_file_id: str) -> list[dict[str, Any]]:
        """
        获取目录下的所有文件（自动分页）
        parent_file_id: 父目录 ID
        """
            
        url = f"{self._api_url}/adrive/v1.0/openFile/list"

        all_items = []
        marker = ""

        while True:
            body = {
                "drive_id": self._drive_id,
                "parent_file_id": parent_file_id,
                "limit": 100,
            }

            if marker: body["marker"] = marker
            result = self._request("POST", url, json=body)

            items = result.get("items", [])
            for item in items:
                item = AlipanAPI._filter_data(item)
                all_items.append(item)
                
            marker = result.get("next_marker")
            if not marker: break

        return all_items

    def get_by_path(self, file_path: str) -> dict[str, Any]:
        """
        根据路径获取资源信息
        """

        if file_path == "/":
            return {
                "file_id": "root",
                "name": "根目录",
                "type": "folder",
            }
        
        url = f"{self._api_url}/adrive/v1.0/openFile/get_by_path"
        body = {
            "drive_id": self._drive_id,
            "file_path": file_path,
        }

        result = self._request("POST", url, json=body)

        return AlipanAPI._filter_data(result)

    def get_file_id(self, file_path: str) -> str:
        """
        获取资源 ID
        """

        file_meta = self.get_by_path(file_path)
        return file_meta.get("file_id")

    def get_download_url(self, file_id: str, headers: dict[str, str] = None, expire_sec: int = 900) -> str:
        """
        获取文件下载链接
        file_id: 文件 ID
        range_header: 范围请求头（可选）
        expire_sec: 过期时间（秒）
        """

        url = f"{self._api_url}/adrive/v1.0/openFile/getDownloadUrl"

        body = {
            "drive_id": self._drive_id,
            "file_id": file_id,
            "expire_sec": expire_sec,
        }

        result = self._request("POST", url, json=body, headers=headers)

        return result["url"]

    def trash(self, file_id: str) -> dict:
        """
        将文件放入回收站
        """

        url = f"{self._api_url}/adrive/v1.0/openFile/recyclebin/trash"

        body = {
            "drive_id": self._drive_id,
            "file_id": file_id,
        }

        result = self._request("POST", url, json=body)

        return {
            "file_id": result.get("file_id"),
            "async_task_id": result.get("async_task_id"),
        }

    def create_source(
        self,
        parent_file_id: str,
        name: str,
        size: int = None,
        type: str = "file",
        check_name_mode: str = "refuse",
        pre_hash: str = None,
        content_hash: str = None,
        content_hash_name: str = "sha1",
        proof_code: str = None,
        proof_version: str = None,
        part_info_list: list = None,
    ):
        """
        创建文件（支持秒传 + 分片上传）
        """

        url = f"{self._api_url}/adrive/v1.0/openFile/create"

        body = {
            "drive_id": self._drive_id,
            "parent_file_id": parent_file_id,
            "name": name,
            "type": type,
            "check_name_mode": check_name_mode,
        }

        # 秒传参数
        if size:
            body["size"] = size
        if pre_hash:
            body["pre_hash"] = pre_hash
        if content_hash:
            body["content_hash"] = content_hash
        if content_hash_name:
            body["content_hash_name"] = content_hash_name
        if proof_code:
            body["proof_code"] = proof_code
        if proof_version:
            body["proof_version"] = proof_version

        # 分片参数
        if part_info_list:
            body["part_info_list"] = part_info_list

        result = self._request("POST", url, json=body)

        return {
            "file_id": result.get("file_id"),
            "upload_id": result.get("upload_id"),
            "parent_file_id": result.get("parent_file_id"),
            "exist": result.get("exist"),
            "rapid_upload": result.get("rapid_upload"),
            "part_info_list": result.get("part_info_list", []),
        }

    def get_upload_url(self, file_id: str, upload_id: str, part_numbers: list):
        """
        刷新上传 URL
        """

        url = f"{self._api_url}/adrive/v1.0/openFile/getUploadUrl"

        body = {
            "drive_id": self._drive_id,
            "file_id": file_id,
            "upload_id": upload_id,
            "part_info_list": [{"part_number": part_number} for part_number in part_numbers],
        }

        result = self._request("POST", url, json=body)

        return {
            "file_id": result.get("file_id"),
            "upload_id": result.get("upload_id"),
            "part_info_list": result.get("part_info_list"),
        }

    def list_uploaded_parts(self, file_id: str, upload_id: str, part_number_marker: int = None):
        """
        列举已上传分片
        """

        url = f"{self._api_url}/adrive/v1.0/openFile/listUploadedParts"

        body = {
            "drive_id": self._drive_id,
            "file_id": file_id,
            "upload_id": upload_id,
        }

        if part_number_marker:
            body["part_number_marker"] = part_number_marker

        result = self._request("POST", url, json=body)

        return {
            "upload_id": result.get("upload_id"),
            "uploaded_parts": result.get("uploaded_parts"),
            "next_part_number_marker": result.get("next_part_number_marker"),
        }

    def complete_upload(self, file_id: str, upload_id: str):
        """
        完成上传
        """

        url = f"{self._api_url}/adrive/v1.0/openFile/complete"

        body = {
            "drive_id": self._drive_id,
            "file_id": file_id,
            "upload_id": upload_id,
        }

        result = self._request("POST", url, json=body)

        return AlipanAPI._filter_data(result)

    def rename(self, file_id: str, new_name: str, check_name_mode: str = "refuse"):
        """
        重命名资源
        file_id: 文件 ID
        new_name: 新名称
        check_name_mode: 检查名称模式（可选）
        """

        url = f"{self._api_url}/adrive/v1.0/openFile/update"

        body = {
            "drive_id": self._drive_id,
            "file_id": file_id,
            "new_name": new_name,
            "check_name_mode": check_name_mode,
        }

        result = self._request("POST", url, json=body)

        return AlipanAPI._filter_data(result)

    def move(self, file_id: str, to_parent_file_id: str, new_name: str = None, check_name_mode: str = "refuse"):
        """
        移动资源
        file_id: 文件 ID
        to_parent_file_id: 目标父文件夹 ID
        new_name: 新名称（可选）
        check_name_mode: 检查名称模式（可选）
        """

        url = f"{self._api_url}/adrive/v1.0/openFile/move"

        body = {
            "drive_id": self._drive_id,
            "file_id": file_id,
            "to_parent_file_id": to_parent_file_id,
            "check_name_mode": check_name_mode,
        }

        if new_name:
            body["new_name"] = new_name
        
        result = self._request("POST", url, json=body)
        
        return {
            "file_id": result.get("file_id"),
            "async_task_id": result.get("async_task_id", ""),
        }

    def copy(self, file_id: str, to_parent_file_id: str, auto_rename: bool = False):
        """
        复制资源
        file_id: 文件 ID
        to_parent_file_id: 目标父文件夹 ID
        auto_rename: 是否自动重命名（可选）
        """

        url = f"{self._api_url}/adrive/v1.0/openFile/copy"

        body = {
            "drive_id": self._drive_id,
            "file_id": file_id,
            "to_parent_file_id": to_parent_file_id,
            "auto_rename": auto_rename,
        }

        result = self._request("POST", url, json=body)

        return {
            "file_id": result.get("file_id"),
            "async_task_id": result.get("async_task_id", ""),
        }
    
    def async_task(self, async_task_id: str):
        """
        查询异步任务状态
        async_task_id: 异步任务 ID
        """
        
        url = f"{self._api_url}/adrive/v1.0/openFile/async_task/get"
        body = {
            "async_task_id": async_task_id,
        }

        result = self._request("POST", url, json=body)

        return result.get("state") == "Succeed"