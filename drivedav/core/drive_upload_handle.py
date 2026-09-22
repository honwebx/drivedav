from abc import ABC, abstractmethod

class DriveUploadHandle(ABC):
    """
    网盘上传抽象接口
    """

    @abstractmethod
    def write(self, data: bytes):
        """
        上传对象
        该方法会被调用来写入数据
        """

        pass

    @abstractmethod
    def close(self):
        """
        完成上传
        该方法会在上传完成时调用
        """

        pass