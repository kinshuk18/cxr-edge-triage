"""S3-compatible storage adapter, including SHA-256 object checksums."""

import asyncio
import base64
import hashlib
from typing import Any

import boto3
from botocore.config import Config

from app.config import settings


class ObjectStore:
    def __init__(self, client: Any = None):
        self.client = client or boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
            config=Config(
                s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"},
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    async def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> str:
        digest = hashlib.sha256(data).hexdigest()
        checksum = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ChecksumSHA256=checksum,
            Metadata={"sha256": digest},
        )
        return digest

    async def get_bytes(self, bucket: str, key: str, max_bytes: int) -> bytes:
        response = await asyncio.to_thread(self.client.get_object, Bucket=bucket, Key=key)
        body = response["Body"]
        try:
            data = await asyncio.to_thread(body.read, max_bytes + 1)
        finally:
            body.close()
        if len(data) > max_bytes:
            raise ValueError("object exceeds configured size cap")
        return data

    async def download_to_file(self, bucket: str, key: str, path: str) -> None:
        await asyncio.to_thread(self.client.download_file, bucket, key, path)
