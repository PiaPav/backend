import os
import uuid
from datetime import datetime
from typing import AsyncIterator

from fastapi import UploadFile

from infrastructure.object_storage.interface import AbstractStorage
from infrastructure.object_storage.object_storage_manager import ObjectStorageManager
from utils.logger import create_logger

log = create_logger("ObjectManagerService")

class ObjectManager:
    def __init__(self, repo: AbstractStorage):
        self.repo = repo

    @staticmethod
    def generate_key(path:str, arg:str, filename: str = None):
        date_path = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"{path}/{arg}/{date_path}/{uuid.uuid4()}"
        if filename:
            extension = os.path.splitext(filename)[1]
            if extension:
                key += extension
        return key

    async def upload(self, fileobj: AsyncIterator[bytes] | UploadFile, size: int = 0 , **metadata) -> str:

        filename = None
        if "filename" in metadata:
            filename = metadata["filename"]
        elif isinstance(fileobj, UploadFile):
            filename = fileobj.filename

        key = self.generate_key(path=metadata["path"], arg=metadata["arg"], filename=filename)
        try:
            if size > 50 * 1024 * 1024:
                await self.repo.stream_upload(key, fileobj)
            else:
                await self.repo.upload_fileobj(key, fileobj)

            return key

        except Exception as e:
            log.error(f"Ошибка {e} при вызовы инфраструктурного слоя в сервисный (ObjectStorage)")
            raise RuntimeError("Ошибка загрузки файла в хранилище") from e

    async def delete(self, key:str):
        await self.repo.delete_file(key)

s3_repo = ObjectStorageManager()
object_manager = ObjectManager(s3_repo)



