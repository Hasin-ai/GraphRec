"""Apply the bucket's lifecycle configuration.

BACKEND_PLAN §24: "Lifecycle rules purge uploads and checkpoints". This applies
the half of that a lifecycle rule can express, and is explicit about the half it
cannot — because a script named `lifecycle` that quietly covered one of two
things would leave the other looking covered.

## What it applies

**Incomplete multipart uploads, aborted after a day.** Bucket-wide, no prefix.
This is the disk leak nobody sees: a training run that dies mid-upload leaves
its parts behind, the parts are not objects so they appear in no listing and in
no `mc du`, and the only symptom is that the volume fills. §9.4's "Disk
exhaustion" row and the `DiskFillingUp` alert are the downstream of exactly
this, and an alert is a detector rather than a fix.

One day rather than seven: nothing here resumes an interrupted upload. A part
that is a day old belongs to a process that is not coming back.

## What it does not, and why the obvious version is wrong

Checkpoints and snapshots are *not* expired here, and the reason is the key
layout rather than an oversight. `graphrec/storage/keys.py` puts the tenant
first — `tenants/{tenant_id}/checkpoints/{job_id}.safetensors` — because a
prefix that begins with the tenant is what makes a bucket policy and a deletion
sweep expressible per tenant. S3 lifecycle filters match a literal prefix and
support no wildcard, so there is no single rule that names "every tenant's
checkpoints"; there is only one rule per tenant, written by something that
enumerates tenants, which is a lifecycle configuration that drifts.

The three ways out, none of them a one-liner, recorded so the next person does
not re-derive them:

1. Tag on write (`graphrec-class=checkpoint`) and filter the rule on the tag.
   Correct, and it changes `ArtifactStore.put_bytes`/`put_file` and both
   implementations, so it is a change to the storage port rather than to this
   script.
2. Reorder keys to `checkpoints/{tenant_id}/…`. One rule, and it gives up the
   invariant `keys.py` is built on.
3. A scheduled sweep that reads the database. The only option that can tell a
   checkpoint belonging to a RUNNING job from one belonging to a finished one —
   and the two look identical in the bucket, which is why a naive age-based
   sweep would delete the resume point of a run that is still going.

Until one of those lands, checkpoints are bounded by the fact that there is one
key per job, overwritten in place, rather than by a rule. Snapshots are not
bounded at all. Both are stated in `docs/PRODUCTION_READINESS.md` as not met.

Usage:
    python scripts/ops/lifecycle.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import boto3
from botocore.config import Config

from graphrec.common.config import get_settings

#: Aborted after this many days. See the note above on why it is not seven.
ABORT_AFTER_DAYS = 1

#: Prefixes a rule here must never expire. A bundle is what an active model
#: version is; deleting one turns a healthy tenant into a permanent fallback,
#: and the registry row would still say the version is ACTIVE.
PROTECTED = ("bundles",)


def configuration() -> dict[str, Any]:
    return {
        "Rules": [
            {
                "ID": "abort-incomplete-uploads",
                "Status": "Enabled",
                # An empty prefix filter is the whole bucket. Spelled as
                # `{"Prefix": ""}` rather than omitted: MinIO and S3 both accept
                # a rule with no filter, and a rule with no filter is one review
                # away from being read as "this rule is unfinished".
                "Filter": {"Prefix": ""},
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": ABORT_AFTER_DAYS},
            }
        ]
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply the bucket lifecycle configuration.")
    parser.add_argument("--dry-run", action="store_true", help="Print it and change nothing.")
    args = parser.parse_args(argv)

    settings = get_settings()
    rules = configuration()

    if args.dry_run:
        print(json.dumps(rules, indent=2))
        return 0

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        # The same addressing decision `graphrec/storage/factory.py` makes, read
        # from the same setting. MinIO is reached by address on the tunnel, and a
        # virtual-host style request would ask DNS for `graphrec.10.10.0.3`.
        config=Config(s3={"addressing_style": "path" if settings.s3_use_path_style else "virtual"}),
    )
    client.put_bucket_lifecycle_configuration(
        Bucket=settings.s3_bucket, LifecycleConfiguration=rules
    )
    print(f"applied {len(rules['Rules'])} lifecycle rule(s) to {settings.s3_bucket}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
