"""Amazon S3 support.

S3 holds files, not tables, so it cannot back a SQL agent the way MySQL or
Snowflake can. Previously a saved S3 connection could be attached to an agent
anyway: is_agent_queryable() reported it as queryable and the SQL agent then
crashed on base64-decoding a NULL password.

S3 is instead an *import* source. Objects are listed here and handed to the
same ingestion pipeline used by manual uploads, after which the resulting
tables are queryable through the normal path.
"""

import io
import os

BROWSABLE_EXTENSIONS = (".csv", ".xlsx", ".xls", ".json")
IMPORTABLE_EXTENSIONS = (".csv", ".xlsx", ".xls")

# Guard against pulling a multi-GB object into memory.
MAX_IMPORT_BYTES = 200 * 1024 * 1024  # 200 MB


class S3Error(RuntimeError):
    pass


def _client(cfg):
    """Build a boto3 S3 client from a normalized connection config."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise S3Error(
            "boto3 is not installed on the server. Add 'boto3' to requirements.txt."
        ) from exc

    access_key = cfg.get("s3_access_key")
    secret_key = cfg.get("s3_secret_key")
    region = cfg.get("s3_region") or "us-east-1"

    session_kwargs = {"region_name": region}
    if access_key and secret_key:
        session_kwargs["aws_access_key_id"] = access_key
        session_kwargs["aws_secret_access_key"] = secret_key
    # With no explicit keys boto3 falls back to the instance role / environment,
    # which is how this should be run on EC2.

    import boto3
    session = boto3.session.Session(**session_kwargs)
    return session.client(
        "s3",
        config=Config(
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=10,
            read_timeout=30,
        ),
    )


def _friendly_error(exc):
    """Map botocore errors to something a user can act on."""
    try:
        from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError
    except ImportError:  # pragma: no cover
        return str(exc)[:300]

    if isinstance(exc, NoCredentialsError):
        return "No AWS credentials were supplied and none are available on the server."

    if isinstance(exc, EndpointConnectionError):
        return "Could not reach AWS. Check the region and the server's network access."

    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        mapping = {
            "InvalidAccessKeyId": "That AWS access key ID does not exist.",
            "SignatureDoesNotMatch": "The AWS secret access key is incorrect.",
            "AccessDenied": (
                "Access denied. The key needs s3:ListBucket on the bucket and "
                "s3:GetObject on its contents."
            ),
            "NoSuchBucket": "That bucket does not exist in this account.",
            "AllAccessDisabled": "Access to this bucket has been disabled.",
            "PermanentRedirect": (
                "Wrong region for this bucket. Set the region the bucket was created in."
            ),
            "AuthorizationHeaderMalformed": (
                "Wrong region for this bucket. Set the region the bucket was created in."
            ),
            "ExpiredToken": "The AWS credentials have expired.",
        }
        if code in mapping:
            return mapping[code]
        message = exc.response.get("Error", {}).get("Message", "")
        return f"{code}: {message}"[:300] if code else str(exc)[:300]

    return str(exc)[:300]


def probe_s3(cfg):
    """Check that the bucket is reachable and listable.

    Returns ``(ok, message)``. Uses list_objects_v2 with MaxKeys=1 rather than
    the resource API's ``.objects.limit(1)`` so a bucket that is empty (or
    whose prefix is empty) still counts as a success.
    """
    bucket = cfg.get("s3_bucket")
    if not bucket:
        return False, "Bucket name is required."

    try:
        client = _client(cfg)
    except S3Error as exc:
        return False, str(exc)

    prefix = (cfg.get("s3_prefix") or "").lstrip("/")

    try:
        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
    except Exception as exc:
        return False, _friendly_error(exc)

    count = response.get("KeyCount", 0)
    where = f"s3://{bucket}/{prefix}" if prefix else f"s3://{bucket}"
    if count:
        return True, f"Connected to {where}."
    return True, f"Connected to {where} (no objects found at this prefix yet)."


def list_objects(cfg, prefix=None, limit=500, only_importable=False):
    """List objects under the connection's prefix.

    Folder-like keys and zero-byte placeholders are skipped.
    """
    bucket = cfg.get("s3_bucket")
    if not bucket:
        raise S3Error("Bucket name is required.")

    effective_prefix = prefix if prefix is not None else (cfg.get("s3_prefix") or "")
    effective_prefix = effective_prefix.lstrip("/")

    client = _client(cfg)
    extensions = IMPORTABLE_EXTENSIONS if only_importable else BROWSABLE_EXTENSIONS

    items = []
    truncated = False
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=effective_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/") or obj["Size"] == 0:
                    continue
                if not key.lower().endswith(extensions):
                    continue

                items.append({
                    "key": key,
                    "name": os.path.basename(key),
                    "size": obj["Size"],
                    "size_label": human_size(obj["Size"]),
                    "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else None,
                    "extension": os.path.splitext(key)[1].lower().lstrip("."),
                    "importable": key.lower().endswith(IMPORTABLE_EXTENSIONS),
                    "too_large": obj["Size"] > MAX_IMPORT_BYTES,
                })

                if len(items) >= limit:
                    truncated = True
                    break
            if truncated:
                break
    except Exception as exc:
        raise S3Error(_friendly_error(exc)) from exc

    items.sort(key=lambda item: item["last_modified"] or "", reverse=True)
    return {"objects": items, "truncated": truncated, "bucket": bucket, "prefix": effective_prefix}


def fetch_object(cfg, key):
    """Download one object into memory.

    Returns ``(filename, BytesIO)``. Refuses objects above MAX_IMPORT_BYTES.
    """
    bucket = cfg.get("s3_bucket")
    if not bucket:
        raise S3Error("Bucket name is required.")
    if not key:
        raise S3Error("Object key is required.")

    client = _client(cfg)

    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        raise S3Error(_friendly_error(exc)) from exc

    size = head.get("ContentLength", 0)
    if size > MAX_IMPORT_BYTES:
        raise S3Error(
            f"{os.path.basename(key)} is {human_size(size)}, above the "
            f"{human_size(MAX_IMPORT_BYTES)} import limit."
        )

    buffer = io.BytesIO()
    try:
        client.download_fileobj(bucket, key, buffer)
    except Exception as exc:
        raise S3Error(_friendly_error(exc)) from exc

    buffer.seek(0)
    return os.path.basename(key), buffer


def human_size(num_bytes):
    if num_bytes is None:
        return ""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
