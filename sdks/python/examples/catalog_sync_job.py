"""Nightly catalog sync from a CSV export (e.g. Shopify/WooCommerce/ERP).

    export GRAPHREC_API_KEY=gr_live_...   # scopes: graphrec_sdk.CATALOG_SYNC_KEY_SCOPES
    python examples/catalog_sync_job.py products.csv

Expected columns: sku,title,price,category,brand,stock
Products missing from the file are disabled so they stop being recommended.
Exit code 1 signals rejected rows or failed disables (useful for cron alerts).
"""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Iterator

from graphrec_sdk import AvailabilityStatus, GraphRec
from graphrec_sdk.ecommerce import CatalogSync


def read_feed(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            in_stock = int(row.get("stock") or 0) > 0
            yield {
                "external_id": row["sku"],
                "title": row["title"],
                "price": row.get("price") or "0",
                "category": row.get("category") or None,
                "availability_status": (
                    AvailabilityStatus.AVAILABLE if in_stock else AvailabilityStatus.OUT_OF_STOCK
                ),
                "metadata": {"brand": row.get("brand")},
            }


def main(feed: Path) -> int:
    logging.basicConfig(level=logging.INFO)
    with GraphRec() as client:
        report = CatalogSync(client).run(
            read_feed(feed),
            disable_missing=True,
            idempotency_key=f"catalog-sync-{feed.stat().st_mtime_ns}",
        )
    print(report.summary())
    for failure in report.upsert.failures:
        print(f"rejected {failure.external_id}: {failure.reason}")
    for sku, message in report.disable_failures.items():
        print(f"could not disable {sku}: {message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(Path(sys.argv[1])))
