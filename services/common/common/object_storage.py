from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
from time import perf_counter
from typing import Any

from common.config import Settings
from common.telemetry import OBJECT_STORAGE_LATENCY


class ObjectStorage(ABC):
    @abstractmethod
    async def put_file(self, key: str, path: Path, checksum_sha256: str) -> str: ...

    @abstractmethod
    async def stream(self, key: str, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def signed_url(self, key: str, expires_seconds: int) -> str: ...


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


class S3ObjectStorage(ObjectStorage):
    def __init__(self, settings: Settings) -> None:
        import boto3

        self.bucket = settings.object_storage_bucket
        self.client = boto3.client(
            "s3", endpoint_url=settings.object_storage_endpoint_url or None,
            region_name=settings.object_storage_region,
            aws_access_key_id=settings.object_storage_access_key or None,
            aws_secret_access_key=settings.object_storage_secret_key or None,
        )

    async def put_file(self, key: str, path: Path, checksum_sha256: str) -> str:
        started = perf_counter()
        try:
            await asyncio.to_thread(self.client.upload_file, str(path), self.bucket, key, ExtraArgs={"Metadata": {"sha256": checksum_sha256}})
            head = await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=key)
            if str(head.get("Metadata", {}).get("sha256") or "") != checksum_sha256:
                raise ValueError(f"checksum metadata verification failed for {key}")
            OBJECT_STORAGE_LATENCY.labels("s3", "put", "ok").observe(perf_counter() - started)
            return f"s3://{self.bucket}/{key}"
        except Exception:
            OBJECT_STORAGE_LATENCY.labels("s3", "put", "error").observe(perf_counter() - started)
            raise

    async def stream(self, key: str, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        started = perf_counter()
        outcome = "ok"
        try:
            response = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
            body = response["Body"]
            while chunk := await asyncio.to_thread(body.read, chunk_size):
                yield chunk
        except Exception:
            outcome = "error"
            raise
        finally:
            OBJECT_STORAGE_LATENCY.labels("s3", "get", outcome).observe(perf_counter() - started)

    async def delete(self, key: str) -> None:
        started = perf_counter()
        try:
            await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)
            OBJECT_STORAGE_LATENCY.labels("s3", "delete", "ok").observe(perf_counter() - started)
        except Exception:
            OBJECT_STORAGE_LATENCY.labels("s3", "delete", "error").observe(perf_counter() - started)
            raise

    async def signed_url(self, key: str, expires_seconds: int) -> str:
        return await asyncio.to_thread(self.client.generate_presigned_url, "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_seconds)


class AzureBlobObjectStorage(ObjectStorage):
    def __init__(self, settings: Settings) -> None:
        from azure.storage.blob.aio import BlobServiceClient

        self.container = settings.object_storage_bucket
        self.service = BlobServiceClient.from_connection_string(settings.azure_blob_connection_string)

    async def put_file(self, key: str, path: Path, checksum_sha256: str) -> str:
        started = perf_counter()
        blob = self.service.get_blob_client(self.container, key)
        try:
            with path.open("rb") as handle:
                await blob.upload_blob(handle, overwrite=True, metadata={"sha256": checksum_sha256})
            properties = await blob.get_blob_properties()
            if str(properties.metadata.get("sha256") or "") != checksum_sha256:
                raise ValueError(f"checksum metadata verification failed for {key}")
            OBJECT_STORAGE_LATENCY.labels("azure-blob", "put", "ok").observe(perf_counter() - started)
            return str(blob.url)
        except Exception:
            OBJECT_STORAGE_LATENCY.labels("azure-blob", "put", "error").observe(perf_counter() - started)
            raise

    async def stream(self, key: str, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        started = perf_counter()
        outcome = "ok"
        try:
            downloader = await self.service.get_blob_client(self.container, key).download_blob()
            async for chunk in downloader.chunks():
                yield chunk
        except Exception:
            outcome = "error"
            raise
        finally:
            OBJECT_STORAGE_LATENCY.labels("azure-blob", "get", outcome).observe(perf_counter() - started)

    async def delete(self, key: str) -> None:
        started = perf_counter()
        try:
            await self.service.get_blob_client(self.container, key).delete_blob()
            OBJECT_STORAGE_LATENCY.labels("azure-blob", "delete", "ok").observe(perf_counter() - started)
        except Exception:
            OBJECT_STORAGE_LATENCY.labels("azure-blob", "delete", "error").observe(perf_counter() - started)
            raise

    async def signed_url(self, key: str, expires_seconds: int) -> str:
        # Account SAS generation needs an account key; deployments may instead
        # expose the controlled streaming API, which is the safe default.
        return ""


def build_object_storage(settings: Settings) -> ObjectStorage:
    provider = str(settings.object_storage_provider or "s3").strip().lower()
    if provider in {"s3", "minio"}:
        return S3ObjectStorage(settings)
    if provider in {"azure", "azure-blob", "blob"}:
        if not settings.azure_blob_connection_string:
            raise ValueError("Azure Blob storage requires AZURE_BLOB_CONNECTION_STRING")
        return AzureBlobObjectStorage(settings)
    raise ValueError(f"Unsupported object-storage provider '{provider}'")
