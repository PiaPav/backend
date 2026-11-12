"""S3 conditional writes retain immutable input, result and pending event."""
from botocore.exceptions import ClientError

from .contracts import PermanentError


class S3ArtifactStore:
    def __init__(self, client, bucket: str):
        self.client, self.bucket = client, bucket

    async def read(self, key: str, limit: int) -> bytes | None:
        try:
            response = await self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise
        async with response["Body"] as stream:
            if response["ContentLength"] > limit:
                raise PermanentError("artifact too large")
            chunks, length = [], 0
            while True:
                chunk = await stream.read(min(65536, limit + 1 - length))
                if not chunk:
                    break
                chunks.append(chunk)
                length += len(chunk)
                if length > limit:
                    raise PermanentError("artifact too large")
            return b"".join(chunks)

    async def put_once(self, key: str, data: bytes) -> bytes:
        try:
            await self.client.put_object(Bucket=self.bucket, Key=key, Body=data,
                                         ContentType="application/json", IfNoneMatch="*")
            return data
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("PreconditionFailed", "412"):
                raise
        existing = await self.read(key, max(len(data), 65536))
        if existing is None:
            raise RuntimeError("conditional object disappeared")
        return existing
