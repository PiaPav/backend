import aioboto3
import os
import zipfile
import tarfile
from utils.config import CONFIG
from pathlib import Path
import asyncio

from utils.logger import create_logger

log = create_logger("ExtractArchive")


async def extract_upload(
    bucket_name: str,
    object_key: str,
    temp_dir: str = "./tmp"):

    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    local_archive_path = temp_dir / os.path.basename(object_key)

    extract_dir = temp_dir / f"{os.path.basename(object_key)}_unzipped"
    extract_dir.mkdir(parents=True, exist_ok=True)

    session = aioboto3.Session()

    async with session.client("s3",
                endpoint_url=f"http://{CONFIG.s3.host}:{CONFIG.s3.port}",
                aws_access_key_id=CONFIG.s3.ACCESS_ID,
                aws_secret_access_key=CONFIG.s3.SECRET_KEY) as s3:
        await s3.download_file(bucket_name, object_key, str(local_archive_path))

    if zipfile.is_zipfile(local_archive_path):
        with zipfile.ZipFile(local_archive_path, "r") as z:
            z.extractall(extract_dir)

    elif tarfile.is_tarfile(local_archive_path):
        with tarfile.open(local_archive_path, "r:*") as t:
            t.extractall(extract_dir)

    else:
        log.error(f"Файл  {local_archive_path} не является архивом")
        raise ValueError(f"Файл  {local_archive_path} не является архивом")

    async with session.client(
                "s3",
                endpoint_url=f"http://{CONFIG.s3.host}:{CONFIG.s3.port}",
                aws_access_key_id=CONFIG.s3.ACCESS_ID,
                aws_secret_access_key=CONFIG.s3.SECRET_KEY,
            ) as s3:

        for file_path in extract_dir.rglob("*"):

            if file_path.is_file():

                rel_path = file_path.relative_to(extract_dir)

                s3_key = f"{object_key}_unzipped/{rel_path.as_posix()}"

                await s3.upload_file(str(file_path), bucket_name, s3_key)

    log.info(f"Uploaded extracted files to prefix: {object_key}_unzipped/")

    return f"{object_key}_unzipped/"


async def main():
    result = await extract_upload(
        bucket_name="default",
        object_key="testone/algorithm.zip"
    )
    print(result)

# asyncio.run(main())
