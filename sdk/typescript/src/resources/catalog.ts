import {
  Check,
  MAX_CATEGORY,
  MAX_DESCRIPTION,
  MAX_EXTERNAL_ID,
  MAX_PRODUCTS_PER_SYNC,
  MAX_TITLE,
} from '../bounds.js';
import type { Transport } from '../transport.js';
import type { CallOptions, CatalogSyncInput, ProductInput, Submission } from '../types.js';
import { decodeSubmission } from './submissions.js';
import type { WireSubmission } from './submissions.js';

const AVAILABILITY = ['in_stock', 'low_stock', 'out_of_stock'] as const;
const MODES = ['upsert', 'upsert_and_disable_missing'] as const;

function wireProduct(product: ProductInput): Record<string, unknown> {
  return {
    external_id: product.externalId,
    title: product.title,
    ...(product.description === undefined ? {} : { description: product.description }),
    ...(product.category === undefined ? {} : { category: product.category }),
    ...(product.brand === undefined ? {} : { brand: product.brand }),
    ...(product.price === undefined ? {} : { price: product.price }),
    ...(product.availability === undefined ? {} : { availability: product.availability }),
    ...(product.active === undefined ? {} : { active: product.active }),
    ...(product.attributes === undefined ? {} : { attributes: product.attributes }),
  };
}

/**
 * The catalogue, on the control plane.
 *
 * One method, because one is what an integration needs: the per-product CRUD on
 * `/v1/products` is session-realm and `[DEV]`-marked — it is the console's, for
 * a person fixing one row. A nightly sync from a tenant's own backend runs at
 * three in the morning and cannot require anyone to be signed in.
 *
 * `mode: 'upsert_and_disable_missing'` treats the payload as the entire
 * catalogue and disables anything absent from it. That is the right mode for a
 * full export and a catastrophic one for a partial page, which is why it is not
 * the default and why this sentence is here.
 */
export class Catalog {
  readonly #transport: Transport;

  constructor(transport: Transport) {
    this.#transport = transport;
  }

  /**
   * Send up to 5,000 products, accepted for processing.
   *
   * Returns the submission at `202`, before any of it has been applied. A repeat
   * of the same `syncId` returns the original submission unchanged.
   */
  async sync(input: CatalogSyncInput, options?: CallOptions): Promise<Submission> {
    const check = new Check()
      .text('sync_id', input.syncId, MAX_EXTERNAL_ID)
      .collection('products', input.products, MAX_PRODUCTS_PER_SYNC)
      .enum('mode', input.mode, MODES);
    input.products?.forEach((product, index) => {
      const at = `products[${index}].`;
      check
        .text(`${at}external_id`, product.externalId, MAX_EXTERNAL_ID)
        .text(`${at}title`, product.title, MAX_TITLE)
        .text(`${at}description`, product.description, MAX_DESCRIPTION, false)
        .text(`${at}category`, product.category, MAX_CATEGORY, false)
        .text(`${at}brand`, product.brand, MAX_CATEGORY, false)
        .enum(`${at}availability`, product.availability, AVAILABILITY);
    });
    check.done('A catalogue sync');

    const wire = await this.#transport.send<WireSubmission>({
      method: 'POST',
      path: '/v1/products:bulk-upsert',
      idempotent: true,
      ...(options === undefined ? {} : { options }),
      body: {
        sync_id: input.syncId,
        products: input.products.map(wireProduct),
        ...(input.mode === undefined ? {} : { mode: input.mode }),
      },
    });
    return decodeSubmission(wire);
  }
}
