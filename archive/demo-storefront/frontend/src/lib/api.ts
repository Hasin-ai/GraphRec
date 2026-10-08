/** The only place the browser talks to the network: same-origin `/api/demo/*`. */
import type { Compare, Envelope, Health, Product, Purchase, Recommendations, RecommendationsUnavailable, Session, Surface } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly correlationId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE = "/api/demo";

async function call<T>(path: string, init: RequestInit = {}): Promise<Envelope<T>> {
  let response: Response;
  try {
    response = await fetch(BASE + path, {
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(init.body ? { "Content-Type": "application/json" } : {}), ...(init.headers ?? {}) },
      ...init,
    });
  } catch (error) {
    throw new ApiError(0, "network", "The storefront server could not be reached.", undefined);
  }
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) {
    const err = (body as { error?: { code?: string; message?: string; correlationId?: string } } | null)?.error;
    throw new ApiError(response.status, err?.code ?? `http_${response.status}`, err?.message ?? `HTTP ${response.status}`, err?.correlationId);
  }
  return body as Envelope<T>;
}

const post = <T>(path: string, json: unknown) => call<T>(path, { method: "POST", body: JSON.stringify(json) });

export const api = {
  health: () => call<Health>("/health").then((e) => e.data),
  session: () => call<Session>("/session").then((e) => e.data),
  setPersona: (persona: string) => post<Session>("/session/persona", { persona }).then((e) => e.data),
  products: (category?: string) => call<Product[]>(`/products${category ? `?category=${encodeURIComponent(category)}` : ""}`).then((e) => e.data),
  product: (id: string) => call<Product>(`/products/${encodeURIComponent(id)}`).then((e) => e.data),
  /** Fire-and-forget telemetry; failures are reported to the caller but never thrown. */
  event: async (body: { action: string; productId?: string; quantity?: number; price?: string; query?: string; surface: Surface }): Promise<boolean> => {
    try {
      await post("/events", body);
      return true;
    } catch {
      return false;
    }
  },
  recommendations: (body: { topN: number; excludeProductIds: string[]; recentProductIds?: string[]; surface: Surface }) =>
    post<Recommendations | RecommendationsUnavailable>("/recommendations", body).then((e) => e.data),
  click: async (body: { requestId: string; productId: string; position: number; surface: Surface }): Promise<boolean> => {
    try {
      await post("/feedback/click", body);
      return true;
    } catch {
      return false;
    }
  },
  purchase: (body: { lines: { productId: string; quantity: number }[]; clientOrderKey: string }) => post<Purchase>("/purchase", { ...body, surface: "cart" }).then((e) => e.data),
  compare: (topN: number, exclude: string[]) => {
    const params = new URLSearchParams({ topN: String(topN) });
    for (const id of exclude) params.append("exclude", id);
    return call<Compare>(`/compare?${params}`).then((e) => e.data);
  },
};

export function isUnavailable(value: Recommendations | RecommendationsUnavailable): value is RecommendationsUnavailable {
  return (value as RecommendationsUnavailable).available === false;
}
