import base64
import os
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken


class Crypto:
    """
    加密/解密（Fernet + PBKDF2）
    """

    def __init__(self, master_password: str):
        self.master_password = master_password.encode()

    def _derive_key(self, salt: bytes) -> bytes:
        """
        使用 PBKDF2 从主密码派生密钥
        """

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=200_000,
            backend=default_backend()
        )
        return base64.urlsafe_b64encode(kdf.derive(self.master_password))

    def encrypt(self, plaintext: str) -> str:
        """
        加密数据，返回 base64(salt + ciphertext)
        """

        salt = os.urandom(16)
        key = self._derive_key(salt)
        f = Fernet(key)

        token = f.encrypt(plaintext.encode())

        return base64.b64encode(salt + token).decode()

    def decrypt(self, ciphertext: str) -> str:
        """
        解密数据，输入 base64(salt + ciphertext)
        """
        
        raw = base64.b64decode(ciphertext)
        salt = raw[:16]
        token = raw[16:]

        key = self._derive_key(salt)
        f = Fernet(key)

        try:
            return f.decrypt(token).decode()
        except InvalidToken:
            raise ValueError("解密失败：密码错误或数据已损坏")
