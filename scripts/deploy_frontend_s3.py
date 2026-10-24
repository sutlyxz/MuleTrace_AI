"""Deploy MuleTrace AI Frontend Dashboard to Amazon S3 for Static Website Hosting."""
from __future__ import annotations

import argparse
import mimetypes
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backend.aws.s3_service import get_s3_client, ensure_s3_bucket, get_default_bucket_name
from app.backend.config import load_environment


def get_mime_type(file_path: Path) -> str:
    """Guess accurate MIME content type for static assets."""
    ext = file_path.suffix.lower()
    mapping = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".ico": "image/x-icon",
        ".txt": "text/plain; charset=utf-8",
    }
    if ext in mapping:
        return mapping[ext]
    guessed, _ = mimetypes.guess_type(str(file_path))
    return guessed or "application/octet-stream"


def deploy_frontend_to_s3(
    bucket_name: str | None = None,
    frontend_dir: Path | None = None,
    dry_run: bool = False,
) -> int:
    env = load_environment(PROJECT_ROOT)
    os.environ.update(env)

    target_bucket = bucket_name or env.get("S3_BUCKET_NAME") or "muletrace-frontend-dashboard"
    source_dir = frontend_dir or (PROJECT_ROOT / "app" / "frontend")

    if not source_dir.is_dir():
        print(f"[!] Error: Frontend directory not found at {source_dir}")
        return 1

    print("=" * 60)
    print("   MuleTrace AI - S3 Frontend Static Hosting Deployer   ")
    print("=" * 60)
    print(f"[*] Source Folder : {source_dir}")
    print(f"[*] Target Bucket : {target_bucket}")
    print(f"[*] Dry Run       : {dry_run}")
    print()

    client = None
    if not dry_run:
        try:
            client = get_s3_client()
            print(f"[*] Checking/Ensuring S3 Bucket '{target_bucket}'...")
            ensure_s3_bucket(bucket_name=target_bucket, client=client)
            print("[+] Bucket ready.")
        except Exception as exc:
            print(f"[!] Warning: Could not verify bucket online: {exc}")

    # Gather files
    files_to_upload = [p for p in source_dir.rglob("*") if p.is_file()]
    print(f"[*] Found {len(files_to_upload)} static files to upload.\n")

    uploaded = 0
    failed = 0

    for file_path in files_to_upload:
        rel_key = str(file_path.relative_to(source_dir)).replace("\\", "/")
        mime = get_mime_type(file_path)

        if dry_run:
            print(f"  [DRY-RUN] Would upload: {rel_key} ({mime})")
            uploaded += 1
            continue

        try:
            with file_path.open("rb") as body:
                client.put_object(
                    Bucket=target_bucket,
                    Key=rel_key,
                    Body=body,
                    ContentType=mime,
                )
            print(f"  [+] Uploaded: {rel_key} ({mime})")
            uploaded += 1
        except Exception as exc:
            print(f"  [!] Failed {rel_key}: {exc}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Deployment Summary: {uploaded} succeeded, {failed} failed.")
    if not dry_run and failed == 0:
        print(f"[+] Static Website Hosting URL (if enabled on S3):")
        print(f"    http://{target_bucket}.s3-website-us-east-1.amazonaws.com")
        print("[+] Connect with Amazon CloudFront distribution for custom HTTPS domain & CDN caching.")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy MuleTrace AI frontend to Amazon S3")
    parser.add_argument("--bucket", type=str, default=None, help="Target S3 bucket name")
    parser.add_argument("--dry-run", action="store_true", help="Simulate upload without network calls")
    args = parser.parse_args()

    sys.exit(deploy_frontend_to_s3(bucket_name=args.bucket, dry_run=args.dry_run))
