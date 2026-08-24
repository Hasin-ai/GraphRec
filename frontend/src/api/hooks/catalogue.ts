/**
 * Products, and the two submission surfaces that feed them.
 *
 * Every response type here comes from `types.gen.ts`. Nothing in this file
 * decides whether a product may be disabled or whether it is eligible for
 * serving — both are server-supplied fields (`can_disable`, `eligible`,
 * `ineligibility`), which is BUILD_PROMPT §10.9's seventh console-only field
 * and §10.4's gate-5 rule in the same place.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';
import { tenantApi } from '../client';
import type { S } from '../schema';

export type Product = S['ProductResponse'];
export type ProductList = S['ProductListResponse'];
export type Submission = S['SubmissionResponse'];

export interface ProductFilters {
  q?: string;
  category?: string;
  availability?: string;
  limit?: number;
  offset?: number;
}

function query(filters: ProductFilters): string {
  const search = new URLSearchParams();
  if (filters.q) search.set('q', filters.q);
  if (filters.category) search.set('category', filters.category);
  if (filters.availability) search.set('availability', filters.availability);
  search.set('limit', String(filters.limit ?? 25));
  search.set('offset', String(filters.offset ?? 0));
  return search.toString();
}

export const productsQuery = (filters: ProductFilters) => ({
  queryKey: ['products', filters] as const,
  queryFn: () => tenantApi.get<ProductList>(`/v1/products?${query(filters)}`),
});

export const productQuery = (externalId: string) => ({
  queryKey: ['product', externalId] as const,
  queryFn: () =>
    tenantApi.get<Product>(`/v1/products/${encodeURIComponent(externalId)}`),
  retry: false,
});

export function useProducts(filters: ProductFilters): UseQueryResult<ProductList> {
  return useQuery(productsQuery(filters));
}

export function useProduct(externalId: string): UseQueryResult<Product> {
  return useQuery(productQuery(externalId));
}

export function createProduct(body: S['CreateProductRequest']): Promise<Product> {
  return tenantApi.post<Product>('/v1/products', body);
}

export function updateProduct(
  externalId: string,
  body: S['CreateProductRequest'],
): Promise<Product> {
  return tenantApi.put<Product>(`/v1/products/${encodeURIComponent(externalId)}`, body);
}

export function disableProduct(
  externalId: string,
  body: S['DisableProductRequest'],
): Promise<Product> {
  return tenantApi.post<Product>(
    `/v1/products/${encodeURIComponent(externalId)}:disable`,
    body,
  );
}

export function bulkUpsertProducts(
  body: S['BulkUpsertProductsRequest'],
): Promise<Submission> {
  return tenantApi.post<Submission>('/v1/products:bulk-upsert', body);
}

/**
 * A mutation that invalidates the product list on success.
 *
 * Invalidating rather than writing into the cache: the server derives
 * `eligible`, `ineligibility` and `can_disable` from state this client does not
 * hold, so a locally-patched row would render a stale eligibility badge — the
 * one field on the page that must not be guessed.
 */
export function useProductMutation<TInput, TOutput>(
  action: (input: TInput) => Promise<TOutput>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: action,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['products'] });
      void client.invalidateQueries({ queryKey: ['product'] });
      void client.invalidateQueries({ queryKey: ['onboarding'] });
    },
  });
}

// ------------------------------------------------------------- submissions

/**
 * §10.8: 2 s, stopping when the submission settles.
 *
 * `refetchInterval` returns `false` once the status is terminal rather than
 * being cleared by an effect, so the polling stops on the same render that
 * shows the final counts — an effect would leave one more request in flight
 * after the page already said "succeeded".
 */
export const submissionQuery = (submissionId: string) => ({
  queryKey: ['submission', submissionId] as const,
  queryFn: () =>
    tenantApi.get<Submission>(`/v1/submissions/${encodeURIComponent(submissionId)}`),
  retry: false,
  refetchInterval: (result: { state: { data?: Submission } }) => {
    const status = result.state.data?.status;
    // `status` is the coarse three-value field the page polls on;
    // `stage` is the five-value `SubmissionStatus` the rail draws. Polling on
    // `stage` would keep asking after a submission that reached `completed`,
    // because `completed` is a stage a failed submission also reaches.
    return status === 'succeeded' || status === 'failed' ? false : 2000;
  },
});

export function useSubmission(submissionId: string): UseQueryResult<Submission> {
  return useQuery(submissionQuery(submissionId));
}
