/**
 * Nightly catalog sync from a CSV export (e.g. Shopify/WooCommerce/ERP).
 *
 *   export GRAPHREC_API_KEY=gr_live_...   # scopes: CATALOG_SYNC_KEY_SCOPES
 *   npm run build && node examples/catalog-sync-job.ts products.csv
 *
 * Expected columns: sku,title,price,category,brand,stock
 * Products missing from the file are disabled so they stop being recommended.
 * Exit code 1 signals rejected rows or failed disables (useful for cron alerts).
 */
import { readFileSync, statSync } from "node:fs";
import { GraphRec, type ProductInput } from "@graphrec/sdk";
import { CatalogSync } from "@graphrec/sdk/ecommerce";

/** Minimal RFC 4180 reader: quoted fields, doubled quotes, CRLF. */
function parseCsv(text: string): Record<string, string>[] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i += 1;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else field += ch;
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  const [header, ...records] = rows.filter((r) => r.some((v) => v !== ""));
  return records.map((values) => Object.fromEntries(header.map((name, i) => [name.trim(), values[i] ?? ""])));
}

function* readFeed(path: string): Generator<ProductInput> {
  const text = readFileSync(path, "utf8").replace(/^﻿/, "");
  for (const row of parseCsv(text)) {
    const inStock = Number(row.stock || 0) > 0;
    yield {
      external_id: row.sku,
      title: row.title,
      price: row.price || "0",
      category: row.category || null,
      availability_status: inStock ? "available" : "out_of_stock",
      metadata: { brand: row.brand || null },
    };
  }
}

async function main(feed: string): Promise<number> {
  const client = new GraphRec();
  const report = await new CatalogSync(client).run(readFeed(feed), {
    disableMissing: true,
    idempotencyKey: `catalog-sync-${statSync(feed).mtimeMs}`,
  });
  console.log(report.summary());
  for (const failure of report.upsert.failures) console.log(`rejected ${failure.external_id}: ${failure.reason}`);
  for (const [sku, message] of Object.entries(report.disableFailures)) console.log(`could not disable ${sku}: ${message}`);
  return report.ok ? 0 : 1;
}

const feed = process.argv[2];
if (!feed) {
  console.error("usage: node examples/catalog-sync-job.ts products.csv");
  process.exit(2);
}
main(feed).then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    console.error(error);
    process.exitCode = 1;
  },
);
