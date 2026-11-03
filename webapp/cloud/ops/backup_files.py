"""Copy every registered Supabase object to the versioned S3 backup bucket."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import boto3
from sqlalchemy import select

from webapp.cloud.db import create_database
from webapp.cloud.db.models import BackupRun, BackupStatus, File
from webapp.cloud.storage import SupabaseBlobStore


def run_backup(database=None, source=None, s3=None, bucket=None) -> tuple[int, int]:
    database = database or create_database()
    source = source or SupabaseBlobStore(
        supabase_url=os.environ["SUPABASE_URL"],
        secret_key=os.environ["SUPABASE_SECRET_KEY"],
        bucket=os.environ.get("SUPABASE_STORAGE_BUCKET", "project-files"),
    )
    s3 = s3 or boto3.client("s3", region_name=os.environ["AWS_BACKUP_REGION"])
    bucket = bucket or os.environ["AWS_BACKUP_BUCKET"]

    with database.transaction() as db:
        run = BackupRun()
        db.add(run)
        db.flush()
        run_id = run.id
        objects = list(db.execute(
            select(File.storage_key, File.size_bytes, File.sha256, File.mime_type)
        ))

    count = total = 0
    try:
        with tempfile.TemporaryDirectory(prefix="sitescribe-backup-") as directory:
            local = Path(directory) / "object"
            for key, expected_size, sha256, mime_type in objects:
                source.download_to(key, local)
                if local.stat().st_size != expected_size:
                    raise RuntimeError(f"source size mismatch for {key}")
                s3.upload_file(
                    str(local), bucket, key,
                    ExtraArgs={"ContentType": mime_type, "Metadata": {"sha256": sha256}},
                )
                copied = s3.head_object(Bucket=bucket, Key=key)
                if copied["ContentLength"] != expected_size:
                    raise RuntimeError(f"backup verification failed for {key}")
                if copied.get("Metadata", {}).get("sha256") != sha256:
                    raise RuntimeError(f"backup checksum metadata failed for {key}")
                count += 1
                total += expected_size
    except Exception as exc:
        with database.transaction() as db:
            record = db.get(BackupRun, run_id)
            record.status = BackupStatus.FAILED
            record.finished_at = datetime.now(timezone.utc)
            record.error = str(exc)[:2000]
        raise

    with database.transaction() as db:
        record = db.get(BackupRun, run_id)
        record.status = BackupStatus.COMPLETE
        record.finished_at = datetime.now(timezone.utc)
        record.object_count = count
        record.byte_count = total
    return count, total


if __name__ == "__main__":
    run_backup()
