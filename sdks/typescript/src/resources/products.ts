import { chunkItems } from "../batching.js";
import { APIError, InputValidationError } from "../errors.js";
import { newIdempotencyKey } from "../ids.js";
import type { BulkUpsertFailure, Product, ProductBulkUpsertResult, ProductInput, ProductList } from "../types.js";
import { Resource, compact } from "./base.js";

const DUPLICATE_REASON = "Duplicate item external_id within batch";

/** Normalise a product for the wire: money as a string, no undefined keys. */
export function prepareProduct(input: ProductInput): Record<string, unknown> {
  if (!input || typeof input !== "object") throw new InputValidationError("A product must be an object");
  const externalId = String(input.external_id ?? "").trim();
  if (!externalId || externalId.length > 100) throw new InputValidationError("external_id must be 1-100 characters");
  const title = String(input.title ?? "").trim();
  if (!title || title.length > 255) throw new InputValidationError(`Product ${JSON.stringify(externalId)}: title must be 1-255 characters`);
  const out: Record<string, unknown> = { external_id: externalId, title };
  if (input.description !== undefined) out.description = input.description;
  if (input.price !== undefined) {
    const price = Number(input.price);
    if (!Number.isFinite(price) || price < 0) throw new InputValidationError(`Product ${JSON.stringify(externalId)}: price must be a non-negative number`);
    out.price = typeof input.price === "string" ? input.price : String(input.price);
  }
  if (input.category !== undefined) {
    if (input.category !== null && input.category.length > 100) throw new InputValidationError(`Product ${JSON.stringify(externalId)}: category is longer than 100 characters`);
    out.category = input.category;
  }
  if (input.is_active !== undefined) out.is_active = input.is_active;
  if (input.availability_status !== undefined) out.availability_status = input.availability_status;
  if (input.metadata !== undefined) {
    if (!input.metadata || typeof input.metadata !== "object" || Array.isArray(input.metadata)) throw new InputValidationError(`Product ${JSON.stringify(externalId)}: metadata must be an object`);
    out.metadata = input.metadata;
  }
  return out;
}

function emptyResult(): ProductBulkUpsertResult {
  return { accepted_count: 0, created_count: 0, updated_count: 0, skipped_count: 0, rejected_count: 0, failures: [], request_count: 0 };
}

export function mergeBulkResults(results: readonly ProductBulkUpsertResult[], duplicates: readonly BulkUpsertFailure[] = []): ProductBulkUpsertResult {
  const merged = emptyResult();
  for (const r of results) {
    merged.accepted_count += r.accepted_count;
    merged.created_count += r.created_count;
    merged.updated_count += r.updated_count;
    merged.skipped_count += r.skipped_count;
    merged.rejected_count += r.rejected_count;
    merged.failures.push(...(r.failures ?? []));
    merged.request_count += 1;
  }
  merged.rejected_count += duplicates.length;
  merged.failures.push(...duplicates);
  return merged;
}

function chunkKey(base: string | undefined, index: number, total: number): string {
  if (base === undefined) return newIdempotencyKey();
  return total === 1 ? base : `${base}:${index + 1}/${total}`;
}

export class Products extends Resource {
  /**
   * Create or update many products (`POST /v1/products:bulk-upsert`).
   *
   * The input is validated locally, de-duplicated by `external_id` (later
   * duplicates are reported as rejected, like the server does), and split into
   * requests that fit the server's body limit. Counts are summed across
   * requests. If a request fails, the thrown `APIError` carries `partialResult`
   * with the totals applied so far.
   */
  async bulkUpsert(products: Iterable<ProductInput>, options: { idempotencyKey?: string } = {}): Promise<ProductBulkUpsertResult> {
    const seen = new Set<string>();
    const unique: Record<string, unknown>[] = [];
    const duplicates: BulkUpsertFailure[] = [];
    for (const raw of products) {
      const item = prepareProduct(raw);
      const id = item.external_id as string;
      if (seen.has(id)) {
        duplicates.push({ external_id: id, reason: DUPLICATE_REASON });
        continue;
      }
      seen.add(id);
      unique.push(item);
    }
    if (!unique.length) throw new InputValidationError("bulkUpsert() needs at least one product");
    const chunks = chunkItems(unique, { envelopeKey: "products", maxBytes: this.client.maxBodyBytes, maxItems: this.client.maxBatchItems, describe: "Product" });
    const results: ProductBulkUpsertResult[] = [];
    for (const [index, chunk] of chunks.entries()) {
      try {
        results.push(
          await this.client.request<ProductBulkUpsertResult>("products.bulk_upsert", {
            json: { products: chunk },
            idempotencyKey: chunkKey(options.idempotencyKey, index, chunks.length),
          }),
        );
      } catch (error) {
        if (error instanceof APIError) error.partialResult = mergeBulkResults(results, duplicates);
        throw error;
      }
    }
    return mergeBulkResults(results, duplicates);
  }

  async list(): Promise<ProductList> {
    return this.client.request<ProductList>("products.list");
  }

  async get(externalId: string): Promise<Product> {
    return this.client.request<Product>("products.get", { params: { external_id: externalId } });
  }

  /** Create or replace one product (`PUT /v1/products/{external_id}`). Idempotent. */
  async upsert(product: ProductInput): Promise<Product> {
    const body = prepareProduct(product);
    return this.client.request<Product>("products.upsert", { params: { external_id: body.external_id as string }, json: body });
  }

  /**
   * Change some fields of an existing product. The server's PATCH needs the
   * whole product, so the current record is read first and merged with `changes`.
   */
  async update(externalId: string, changes: Partial<Omit<ProductInput, "external_id">>): Promise<Product> {
    const defined = compact(changes as Record<string, unknown>);
    if (!Object.keys(defined).length) throw new InputValidationError("update() needs at least one field to change");
    const current = await this.get(externalId);
    const merged: ProductInput = {
      external_id: current.external_id,
      title: current.title,
      description: current.description,
      price: current.price,
      category: current.category,
      is_active: current.is_active,
      availability_status: current.availability_status,
      metadata: current.metadata,
      ...(defined as Partial<ProductInput>),
    };
    const body = prepareProduct(merged);
    return this.client.request<Product>("products.update", { params: { external_id: externalId }, json: body });
  }

  /** Stop serving a product immediately (`POST /v1/products/{external_id}:disable`). */
  async disable(externalId: string): Promise<Product> {
    return this.client.request<Product>("products.disable", { params: { external_id: externalId } });
  }
}
