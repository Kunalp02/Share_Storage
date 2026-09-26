from __future__ import annotations

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from storage_service.core.exceptions import ServiceError
from storage_service.settings import Settings


class S3ObjectStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint or None,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        )

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._settings.s3_bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._settings.s3_bucket)

    def presign_put(self, storage_key: str, content_type: str) -> str:
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._settings.s3_bucket, "Key": storage_key, "ContentType": content_type},
            ExpiresIn=self._settings.presign_expiry_seconds,
        )

    def presign_get(self, storage_key: str) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._settings.s3_bucket, "Key": storage_key},
            ExpiresIn=self._settings.presign_expiry_seconds,
        )

    def put_bytes(self, storage_key: str, body: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._settings.s3_bucket,
            Key=storage_key,
            Body=body,
            ContentType=content_type,
        )

    def get_bytes(self, storage_key: str, max_bytes: int) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._settings.s3_bucket, Key=storage_key)
        except ClientError as exc:
            raise ServiceError("OBJECT_NOT_FOUND", f"Object not found in storage: {exc}", 404) from exc
        return response["Body"].read(max_bytes + 1)

    def head_object(self, storage_key: str) -> int:
        try:
            response = self._client.head_object(Bucket=self._settings.s3_bucket, Key=storage_key)
            return int(response.get("ContentLength") or 0)
        except ClientError as exc:
            raise ServiceError("OBJECT_NOT_FOUND", f"Object not found in storage: {exc}", 404) from exc

    def delete_object(self, storage_key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._settings.s3_bucket, Key=storage_key)
        except ClientError:
            return
