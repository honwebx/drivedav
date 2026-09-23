import math
import time
import requests
from ...core.drive_upload_handle import DriveUploadHandle
from .error import AlipanError

_CHUNK_SIZE = 4 * 1024 * 1024
_UPLOAD_URL_TTL = 3600


class AlipanUploadHandle(DriveUploadHandle):

    def __init__(self, api, parent_file_id, file_name, file_size=None):
        self._api = api
        self._file_size = file_size

        part_info_list = None
        if file_size:
            num_parts = math.ceil(file_size / _CHUNK_SIZE)
            part_info_list = [{"part_number": i} for i in range(1, num_parts + 1)]

        create_resp = self._api.create_source(
            parent_file_id=parent_file_id,
            name=file_name,
            size=file_size,
            part_info_list=part_info_list,
        )
        self._file_id = create_resp["file_id"]
        self._upload_id = create_resp.get("upload_id")
        self._exist = create_resp.get("exist", False)
        self._rapid_upload = create_resp.get("rapid_upload", False)
        self._aborted = self._exist or self._rapid_upload or not self._upload_id

        self._part_urls = {}
        for part in create_resp.get("part_info_list") or []:
            self._part_urls[part["part_number"]] = part["upload_url"]

        self._urls_created_at = time.time()

        self._part_number = 1
        self._buffer = bytearray()

    def _get_part_url(self, part_number: int) -> str:
        """
        获取分片上传地址
        """

        url = self._part_urls.pop(part_number, None)
        if url and time.time() - self._urls_created_at < _UPLOAD_URL_TTL:
            return url

        resp = self._api.get_upload_url(
            file_id=self._file_id,
            upload_id=self._upload_id,
            part_numbers=[part_number],
        )
        parts = resp.get("part_info_list") or []
        if parts:
            return parts[0]["upload_url"]
        raise Exception(f"无法获取分片{part_number}的上传URL")

    def _upload_part(self, part_number: int, data: bytes):
        """
        上传分片
        """

        try:
            upload_url = self._get_part_url(part_number)
            resp = requests.put(upload_url, data=data)
            resp.raise_for_status()
        except requests.RequestException as e:
            self._abort()
            raise AlipanError.parse_response(getattr(e, "response", None), e) from e
        except Exception as e:
            self._abort()
            raise

    def write(self, data: bytes):
        """
        写入数据到缓冲区，当缓冲区达到 CHUNK_SIZE 时自动上传
        """

        if self._aborted:
            return

        self._buffer.extend(data)

        while len(self._buffer) >= _CHUNK_SIZE:
            chunk = bytes(self._buffer[:_CHUNK_SIZE])
            del self._buffer[:_CHUNK_SIZE]
            self._upload_part(self._part_number, chunk)
            self._part_number += 1

    def close(self):
        """
        完成上传
        上传剩余数据并通知服务器合并文件
        """

        if self._aborted:
            return

        if self._buffer:
            self._upload_part(self._part_number, bytes(self._buffer))

        self._api.complete_upload(self._file_id, self._upload_id)
        self._abort()

    def _abort(self):
        """
        上传失败
        清理资源
        """
        
        self._aborted = True
        self._buffer.clear()