import uuid
import tempfile
import zipfile
import tarfile
from pathlib import Path

from fastapi import UploadFile

from infrastructure.object_storage.interface import AbstractStorage
from infrastructure.object_storage.object_storage_manager import ObjectStorageManager
from utils.logger import create_logger


log = create_logger("ObjectManagerService")

class ObjectManager:
    def __init__(self, repo: AbstractStorage):
        self.repo = repo

    @staticmethod
    def generate_key(user:str, filename: str, tag:str = None):
        key = f"{user}/{filename}/{uuid.uuid4()}/{tag}"
        return key


    async def upload(self, fileobj:UploadFile, **metadata) -> str:

        filename = metadata.get("filename", "zero")
        user = metadata.get("path","-1")

        key = self.generate_key(user=user, filename=filename)
        try:
            await self.repo.upload_fileobj(key, fileobj)

            return key

        except Exception as e:
            log.error(f"Ошибка {e} при вызовы инфраструктурного слоя в сервисный (ObjectStorage)")
            raise RuntimeError("Ошибка загрузки файла в хранилище") from e


    async def delete(self, key:str):
        await self.repo.delete_file(key)


    async def upload_repozitory(
        self,
        fileobj: UploadFile,
        filename:str,
        user:str
    ):

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            temp_archive_path = Path(tmp_file.name)

            if isinstance(fileobj, UploadFile):
                while chunk := await fileobj.read(1024 * 1024):
                    tmp_file.write(chunk)
            else:
                async for chunk in fileobj:
                    tmp_file.write(chunk)

        with tempfile.TemporaryDirectory() as tmpdir:
            extract_dir = Path(tmpdir)

            if zipfile.is_zipfile(temp_archive_path):
                with zipfile.ZipFile(temp_archive_path, "r") as z:
                    z.extractall(extract_dir)

            elif tarfile.is_tarfile(temp_archive_path):
                with tarfile.open(temp_archive_path, "r:*") as t:
                    t.extractall(extract_dir)

            else:
                temp_archive_path.unlink(missing_ok=True)
                raise ValueError("Файл не является ZIP или TAR архивом")

            uploaded = []

            base_path = self.generate_key(user,filename)

            for file_path in extract_dir.rglob("*"):

                if file_path.is_file():
                    rel_path = file_path.relative_to(extract_dir)

                    s3_key = f"{base_path}/unpacked/{rel_path.as_posix()}"

                    await self.repo.upload_file_with_path(
                        key=s3_key,
                        filepath=str(file_path)
                    )
                    uploaded.append(s3_key)

        temp_archive_path.unlink(missing_ok=True)

        return {
            "uploaded": uploaded,
            "total": len(uploaded)
        }


s3_repo = ObjectStorageManager()
object_manager = ObjectManager(s3_repo)


"""import io
from fastapi import UploadFile
import asyncio

zip_bytes = open("/home/linola/Документы/algorithm.zip", "rb").read()
buffer = io.BytesIO(zip_bytes)

fake_upload = UploadFile(
    filename="test.zip",
    file=buffer
)
async def main():
    await object_manager.upload_repozitory(fileobj=fake_upload, path="path", arg="arg")

asyncio.run(main())"""

