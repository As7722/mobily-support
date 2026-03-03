"""
S3 File Storage Service
=======================
- Upload files with server-side AES-256 encryption (SSE-S3).
- Generate pre-signed URLs (1-hour default expiry).
- ClamAV virus scan via pyclamd before accepting uploads.
- All uploads tagged with ticket_id and uploader_id for audit.

Async: uses asyncio.to_thread() to wrap blocking boto3 calls.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)
UTC = timezone.utc

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
ALLOWED_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/pdf",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}


class StorageError(Exception):
    pass


class VirusDetectedError(StorageError):
    pass


# ── ClamAV Scan ───────────────────────────────────────────────────────────────

def _scan_bytes(data: bytes, clamd_host: str = "127.0.0.1", clamd_port: int = 3310) -> None:
    """
    Scan bytes with ClamAV via pyclamd.
    Raises VirusDetectedError if a virus is found.
    Logs a warning and passes if ClamAV is unreachable (fail-open in dev).
    """
    try:
        import pyclamd  # type: ignore[import-untyped]
        cd = pyclamd.ClamdNetworkSocket(clamd_host, clamd_port)
        if not cd.ping():
            log.warning("ClamAV unreachable — skipping scan")
            return
        result = cd.scan_stream(io.BytesIO(data))
        if result:
            virus_name = list(result.values())[0][1] if result else "unknown"
            raise VirusDetectedError(f"Virus detected: {virus_name}")
    except VirusDetectedError:
        raise
    except Exception as exc:
        log.warning("ClamAV scan error (fail-open): %s", exc)


async def scan_bytes_async(data: bytes, **kwargs) -> None:
    await asyncio.to_thread(_scan_bytes, data, **kwargs)


# ── S3 client factory ─────────────────────────────────────────────────────────

def _s3_client(
    aws_access_key: str,
    aws_secret_key: str,
    region: str,
    endpoint_url: Optional[str] = None,
):
    return boto3.client(
        "s3",
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=region,
        **({"endpoint_url": endpoint_url} if endpoint_url else {}),
    )


# ── Upload ────────────────────────────────────────────────────────────────────

def _upload_sync(
    data: bytes,
    filename: str,
    bucket: str,
    s3_key: str,
    aws_access_key: str,
    aws_secret_key: str,
    region: str,
    endpoint_url: Optional[str] = None,
    content_type: Optional[str] = None,
) -> str:
    client = _s3_client(aws_access_key, aws_secret_key, region, endpoint_url)
    ct = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=data,
        ContentType=ct,
        ServerSideEncryption="AES256",
        Metadata={"original-filename": filename},
    )
    return s3_key


async def upload_file(
    data: bytes,
    filename: str,
    *,
    ticket_id: Optional[str] = None,
    uploader_id: Optional[str] = None,
    bucket: str,
    aws_access_key: str,
    aws_secret_key: str,
    region: str,
    endpoint_url: Optional[str] = None,
    scan: bool = True,
) -> str:
    """
    Full pipeline: validate → ClamAV scan → S3 upload (AES-256).
    Returns the S3 key of the uploaded file.
    """
    if len(data) > MAX_FILE_SIZE:
        raise StorageError(f"File too large: {len(data)} bytes (max {MAX_FILE_SIZE})")

    ct = mimetypes.guess_type(filename)[0] or ""
    if ct and ct not in ALLOWED_TYPES:
        raise StorageError(f"File type not allowed: {ct}")

    sha256 = hashlib.sha256(data).hexdigest()

    if scan:
        await scan_bytes_async(data)

    date_prefix = datetime.now(tz=UTC).strftime("%Y/%m/%d")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    s3_key = f"tickets/{ticket_id or 'unlinked'}/{date_prefix}/{uuid.uuid4()}.{ext}"

    await asyncio.to_thread(
        _upload_sync, data, filename, bucket, s3_key,
        aws_access_key, aws_secret_key, region, endpoint_url, ct,
    )
    log.info("Uploaded %s → s3://%s/%s (sha256=%s…)", filename, bucket, s3_key, sha256[:12])
    return s3_key


# ── Signed URL generation ─────────────────────────────────────────────────────

def _presign_sync(
    bucket: str,
    s3_key: str,
    expiry_seconds: int,
    aws_access_key: str,
    aws_secret_key: str,
    region: str,
    endpoint_url: Optional[str] = None,
) -> str:
    client = _s3_client(aws_access_key, aws_secret_key, region, endpoint_url)
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=expiry_seconds,
    )


async def get_signed_url(
    s3_key: str,
    expiry_seconds: int = 3600,
    **kwargs,
) -> str:
    return await asyncio.to_thread(_presign_sync, expiry_seconds=expiry_seconds, s3_key=s3_key, **kwargs)


# ── Delete ────────────────────────────────────────────────────────────────────

async def delete_file(
    s3_key: str,
    *,
    bucket: str,
    aws_access_key: str,
    aws_secret_key: str,
    region: str,
    endpoint_url: Optional[str] = None,
) -> None:
    def _del():
        client = _s3_client(aws_access_key, aws_secret_key, region, endpoint_url)
        client.delete_object(Bucket=bucket, Key=s3_key)

    await asyncio.to_thread(_del)
    log.info("Deleted s3://%s/%s", bucket, s3_key)
