import hashlib
import base64
import os

def get_proof_range(access_token: str, size: int):
    """
    计算阿里云盘 proof_code 的范围。
    """

    if size == 0:
        return 0, 0

    md5_hex = hashlib.md5(access_token.encode("utf-8")).hexdigest()
    prefix16 = md5_hex[:16]
    tmp_int = int(prefix16, 16)

    start = tmp_int % size
    end = start + 8
    if end > size:
        end = size

    return start, end

def compute_proof_code(local_path: str, access_token: str) -> str:
    """
    计算阿里云盘 proof_code。
    """
    
    size = os.path.getsize(local_path)
    start, end = get_proof_range(access_token, size)

    if size == 0:
        return ""

    with open(local_path, "rb") as f:
        f.seek(start)
        data = f.read(end - start)

    return base64.b64encode(data).decode("utf-8")

