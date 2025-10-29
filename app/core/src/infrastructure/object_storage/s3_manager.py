import boto3
from botocore.exceptions import ClientError
from fastapi.concurrency import run_in_threadpool
from fastapi import UploadFile

from interface import AbstractStorage
from utils.config import CONFIG
from utils.logger import create_logger

log = create_logger("ObjectStorageManager")


class ObjectStorageManager(AbstractStorage):
    def __init__(self, endpoint_url: str = f"http://localhost:{CONFIG.}",
                 access_key_id: str = CONFIG.s3.ID,
                 secret_access_key: str = CONFIG.s3.SECRET_KEY,
                 bucket: str = CONFIG.s3.BUCKET):

        self.endpoint_url = endpoint_url
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.bucket = bucket

        session = boto3.session.Session()
        self.s3 = session.client(
            service_name="s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
        )
        self.bucket = bucket

    async def upload_fileobj(self, key: str, fileobj: UploadFile)->None:
        try:
            await run_in_threadpool(self.s3.upload_fileobj,
                                fileobj.file,
                                    self.bucket,
                                    key)
            log.info(f"Файл {fileobj.filename} отправлен")

        except ClientError as e:
            log.error(f"Ошибка при загрузке файла {fileobj.filename} : {e}")


    async def delete_file(self, file_key)->None:
        try:
            await run_in_threadpool(
                self.s3.delete_object,
                Bucket=self.bucket,
                Key=file_key)
            log.info(f"Файл {file_key} удален")

        except ClientError as e:
            log.error(f"Ошибка при удалении файла '{file_key}': {e}")
            raise

s3manager = ObjectStorageManager()
