/**
 * Catalog synchronisation from a source of truth (PIM, ERP, Shopify/WooCommerce export...).
 *
 *     const report = await new CatalogSync(client).run(rows.map(toProduct), { disableMissing: true });
 *     console.log(report.summary());
 */
import type { GraphRec } from "../client.js";
import { APIError, InputValidationError } from "../errors.js";
import { prepareProduct } from "../resources/products.js";
import type { ProductBulkUpsertResult, ProductInput } from "../types.js";

export interface CatalogSyncOptions {
  /** Active products absent from this feed are disabled so they stop being recommended. */
  disableMissing?: boolean;
  /** Allow an empty feed with `disableMissing` (it would disable the whole catalog). */
  allowEmpty?: boolean;
  idempotencyKey?: string;
}

export class CatalogSyncReport {
  constructor(
    readonly upsert: ProductBulkUpsertResult,
    /** Active products that were not in the feed and have been disabled. */
    readonly disabledIds: string[],
    /** Products that could not be disabled, with the error message. */
    readonly disableFailures: Record<string, string>,
    readonly durationMs: number,
  ) {}

  get ok(): boolean {
    return this.upsert.failures.length === 0 && Object.keys(this.disableFailures).length === 0;
  }

  summary(): string {
    const u = this.upsert;
    return (
      `created=${u.created_count} updated=${u.updated_count} rejected=${u.rejected_count} ` +
      `disabled=${this.disabledIds.length} disable_failures=${Object.keys(this.disableFailures).length} ` +
      `requests=${u.request_count} in ${(this.durationMs / 1000).toFixed(1)}s`
    );
  }
}

export class CatalogSync {
  constructor(private readonly client: GraphRec) {}

  async run(products: Iterable<ProductInput>, options: CatalogSyncOptions = {}): Promise<CatalogSyncReport> {
    const started = Date.now();
    const items = Array.from(products);
    for (const item of items) prepareProduct(item);
    if (!items.length && options.disableMissing && !options.allowEmpty) {
      throw new InputValidationError("Refusing to sync an empty feed with disableMissing (it would disable the whole catalog). Pass allowEmpty: true if that is intended.");
    }
    const upsert = items.length
      ? await this.client.products.bulkUpsert(items, { idempotencyKey: options.idempotencyKey })
      : { accepted_count: 0, created_count: 0, updated_count: 0, skipped_count: 0, rejected_count: 0, failures: [], request_count: 0 };
    const disabledIds: string[] = [];
    const disableFailures: Record<string, string> = {};
    if (options.disableMissing) {
      const feed = new Set(items.map((i) => String(i.external_id).trim()));
      const { items: existing } = await this.client.products.list();
      for (const product of existing) {
        if (!product.is_active || feed.has(product.external_id)) continue;
        try {
          await this.client.products.disable(product.external_id);
          disabledIds.push(product.external_id);
        } catch (error) {
          disableFailures[product.external_id] = error instanceof APIError ? error.message : String(error);
        }
      }
    }
    return new CatalogSyncReport(upsert, disabledIds, disableFailures, Date.now() - started);
  }
}
