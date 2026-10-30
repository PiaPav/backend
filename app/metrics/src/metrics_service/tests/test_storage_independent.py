import asyncio
from unittest.mock import AsyncMock

import pytest
from botocore.exceptions import ClientError

from metrics_service.contracts import PermanentError
from metrics_service.s3_adapter import S3ArtifactStore


class Stream:
    def __init__(self, data):
        self.data = data
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def read(self, size):
        data, self.data = self.data[:size], self.data[size:]
        return data


def test_conditional_conflict_returns_existing_immutable_artifact():
    async def scenario():
        client = AsyncMock()
        client.put_object.side_effect = ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        stream = Stream(b"original")
        client.get_object.return_value = {"ContentLength": 8, "Body": stream}
        store = S3ArtifactStore(client, "artifacts")
        assert await store.put_once("key", b"replacement") == b"original"
        assert client.put_object.await_args.kwargs["IfNoneMatch"] == "*"
        assert stream.closed
    asyncio.run(scenario())


@pytest.mark.parametrize("reported_size", [2, 20])
def test_oversize_body_rejected_and_stream_closed(reported_size):
    async def scenario():
        client = AsyncMock()
        stream = Stream(b"0123456789")
        client.get_object.return_value = {"ContentLength": reported_size, "Body": stream}
        with pytest.raises(PermanentError, match="too large"):
            await S3ArtifactStore(client, "artifacts").read("key", 5)
        assert stream.closed
    asyncio.run(scenario())


def test_missing_object_is_distinguished_from_infrastructure_failure():
    async def scenario():
        client = AsyncMock()
        store = S3ArtifactStore(client, "artifacts")
        client.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        assert await store.read("missing", 5) is None
        client.get_object.side_effect = ClientError({"Error": {"Code": "ServiceUnavailable"}}, "GetObject")
        with pytest.raises(ClientError):
            await store.read("missing", 5)
    asyncio.run(scenario())
