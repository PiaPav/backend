from typing import AsyncIterator, Optional

import aioboto3

from infrastructure.object_storage.interface import AbstractStorage
from utils.config import CONFIG
from utils.logger import create_logger

log = create_logger("ObjectStorageManagerInfra")


class ObjectStorageManager(AbstractStorage):
    def __init__(self, endpoint_url: str = f"http://{CONFIG.s3.host}:{CONFIG.s3.port}",
                 access_key_id: str = CONFIG.s3.ACCESS_ID,
                 secret_access_key: str = CONFIG.s3.SECRET_KEY,
                 bucket: str = CONFIG.s3.BUCKET,
                 ):

        self.endpoint_url = endpoint_url
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.bucket = bucket
        self.s3_config = {"service_name": "s3",
                          "endpoint_url": self.endpoint_url,
                          "aws_access_key_id": self.access_key_id,
                          "aws_secret_access_key": self.secret_access_key}

    async def get_filenames(self, dir_path: str) -> list[str]:
        """Получение имен всех файлов в 'директории'"""
        async with aioboto3.Session().client(**self.s3_config) as s3:
            try:
                response = await s3.list_objects_v2(
                    Bucket=self.bucket,
                    Prefix=dir_path
                )
                return [obj["Key"] for obj in response.get("Contents", [])]
            except Exception as e:
                log.error(f"Ошибка получения файлов в {dir_path}: {e}")
                raise

    async def stream_read(self, file_key: str, chunk_size: Optional[int] = 1024 * 1024,
                          decode: Optional[str] = None) -> AsyncIterator[bytes]:
        """Асинхронный итератор по файлу"""
        async with aioboto3.Session().client(**self.s3_config) as s3:
            try:
                response = await s3.get_object(Bucket=self.bucket, Key=file_key)
                stream = response["Body"]

                async for chunk in stream.iter_chunks(chunk_size=chunk_size):
                    if not chunk:
                        break

                    if decode:
                        yield chunk.decode(decode)
                    else:
                        yield chunk

            except s3.exceptions.NoSuchKey:
                raise FileNotFoundError(f"Файл {file_key} не найден в бакете {self.bucket}")

    async def read(self, file_key: str):
        """Получение файла"""
        async with aioboto3.Session().client(**self.s3_config) as s3:
            try:
                response = await s3.get_object(Bucket=self.bucket, Key=file_key)
                async with response["Body"] as stream:
                    return await stream.read()

            except s3.exceptions.NoSuchKey:
                raise FileNotFoundError(f"Файл {file_key} не найден в бакете {self.bucket}")
