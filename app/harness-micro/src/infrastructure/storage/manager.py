import aioboto3
from aiobotocore.client import AioBaseClient
from botocore.config import Config

from .interface import S3Interface


class S3Manager(S3Interface):

    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str) -> None:
        self.bucket = bucket
        self.session = aioboto3.Session()
        self._context = None
        self.client: AioBaseClient | None = None

        self._client_kwargs = {
            "endpoint_url": endpoint_url,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "config": Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        }

    async def create(self, key: str, data: bytes) -> None:
        async with self.session.client("s3", **self._client_kwargs) as client:
            await client.put_object(Bucket=self.bucket, Key=key, Body=data)

    async def read(self, key: str) -> bytes:
        async with self.session.client("s3", **self._client_kwargs) as client:
            response = await client.get_object(Bucket=self.bucket, Key=key)
            async with response["Body"] as stream:
                return await stream.read()

    async def update(self, key: str, data: bytes) -> None:
        await self.create(key, data)

    async def delete(self, key: str) -> None:
        async with self.session.client("s3", **self._client_kwargs) as client:
            await client.delete_object(Bucket=self.bucket, Key=key)
