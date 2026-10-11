"""Upload the storefront's film covers to a RustFS (S3-compatible) bucket and write data/covers.json.

Covers are named by IMDb id (``0114709.jpg`` = Toy Story). Only covers for films in
data/films.json are uploaded (about 7.7k of the 62k files); films without one keep the placeholder.
The bucket gets an anonymous read-only policy so the browser can load ``<endpoint>/<bucket>/<key>``.

    python scripts/upload_covers.py --covers-dir ../../covers/covers \\
        --endpoint http://localhost:9000 --access-key rustfsadmin --secret-key rustfsadmin

Re-running skips objects already in the bucket with the same size.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

DATA = Path(__file__).resolve().parent.parent / "data"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--covers-dir", type=Path, required=True)
    p.add_argument("--endpoint", default=os.getenv("RUSTFS_ENDPOINT", "http://localhost:9000"))
    p.add_argument("--access-key", default=os.getenv("RUSTFS_ACCESS_KEY", "rustfsadmin"))
    p.add_argument("--secret-key", default=os.getenv("RUSTFS_SECRET_KEY", "rustfsadmin"))
    p.add_argument("--bucket", default=os.getenv("REEL_COVERS_BUCKET", "reel-covers"))
    p.add_argument("--workers", type=int, default=16)
    args = p.parse_args()

    films = json.loads((DATA / "films.json").read_text(encoding="utf-8"))
    wanted: dict[str, Path] = {}
    for f in films:
        imdb = (f.get("imdbId") or "").zfill(7)
        path = args.covers_dir / f"{imdb}.jpg"
        if imdb.strip("0") and path.is_file():
            wanted[f["id"]] = path
    print(f"{len(wanted)}/{len(films)} films have a cover in {args.covers_dir}")
    if not wanted:
        print("Nothing to upload: check --covers-dir.", file=sys.stderr)
        return 1

    s3 = boto3.client("s3", endpoint_url=args.endpoint, aws_access_key_id=args.access_key,
                      aws_secret_access_key=args.secret_key, region_name="us-east-1",
                      config=Config(s3={"addressing_style": "path"}, max_pool_connections=args.workers))
    try:
        s3.head_bucket(Bucket=args.bucket)
    except ClientError:
        s3.create_bucket(Bucket=args.bucket)
        print(f"created bucket {args.bucket}")
    s3.put_bucket_policy(Bucket=args.bucket, Policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"AWS": ["*"]}, "Action": ["s3:GetObject"],
                       "Resource": [f"arn:aws:s3:::{args.bucket}/*"]}],
    }))

    existing: dict[str, int] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=args.bucket):
        for o in page.get("Contents", []):
            existing[o["Key"]] = o["Size"]

    def put(path: Path) -> str:
        key = path.name
        if existing.get(key) == path.stat().st_size:
            return "skip"
        s3.upload_file(str(path), args.bucket, key, ExtraArgs={
            "ContentType": "image/jpeg", "CacheControl": "public, max-age=31536000, immutable"})
        return "put"

    done = {"put": 0, "skip": 0}
    with ThreadPoolExecutor(args.workers) as pool:
        for i, r in enumerate(pool.map(put, wanted.values()), 1):
            done[r] += 1
            if i % 500 == 0:
                print(f"  {i}/{len(wanted)}")
    print(f"uploaded {done['put']}, already there {done['skip']}")

    manifest = {film_id: path.name for film_id, path in wanted.items()}
    (DATA / "covers.json").write_text(json.dumps(manifest, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print(f"wrote {DATA / 'covers.json'}; set REEL_COVERS_BASE_URL=<browser-visible endpoint>/{args.bucket}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
