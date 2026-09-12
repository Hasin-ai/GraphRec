/** Wire types for the storefront API (`/api/demo/*`). Mirrors app/schemas.py. */

export type ProofStatus = "model_verified" | "serving_preview" | "catalog_fallback";
export type Surface = "catalog" | "product_detail" | "cart" | "order" | "compare";

export interface Persona {
  key: string;
  name: string;
  blurb: string;
  color: string;
  userId: string | null;
}

export interface Session {
  persona: Persona;
  sessionId: string;
  personas: Persona[];
}

export interface Product {
  externalId: string;
  title: string;
  description: string | null;
  price: string;
  category: string;
  isActive: boolean;
  availabilityStatus: string;
  available: boolean;
  brand: string | null;
  size: string | null;
  tags: string[];
  accent: string | null;
}

export interface RecommendedProduct extends Product {
  position: number;
}

export interface Provenance {
  requestId: string;
  modelVersionId: string | null;
  rawStrategy: string;
  fallbackUsed: boolean;
  fallbackTier: string;
  proofStatus: ProofStatus;
  excludedCount: number;
  omittedProductCount: number;
  impressionEventId: string | null;
}

export interface Recommendations {
  items: RecommendedProduct[];
  provenance: Provenance;
}

export interface RecommendationsUnavailable {
  available: false;
  reason: string;
  correlationId: string | null;
}

export interface PurchaseLine {
  productId: string;
  title: string;
  quantity: number;
  unitPrice: string;
  lineTotal: string;
  eventId: string;
}

export interface Purchase {
  orderId: string;
  lines: PurchaseLine[];
  total: string;
  acceptedCount: number;
  duplicateCount: number;
  rejectedCount: number;
}

export interface CompareItem {
  position: number;
  externalId: string;
  title: string;
  category: string;
  price: string;
  accent: string | null;
  shared: boolean;
}

export interface CompareColumn {
  persona: Persona;
  items: CompareItem[];
  provenance: Provenance | null;
  repeatable: boolean | null;
  error: string | null;
}

export interface PairSimilarity {
  a: string;
  b: string;
  overlap: number;
  jaccard: number;
}

export interface CompareSummary {
  topN: number;
  excludedProductIds: string[];
  uniqueProducts: number;
  slots: number;
  distinctOrderings: number;
  knownPersonasIdentical: boolean;
  allRepeatable: boolean | null;
  anyModelVersion: boolean;
  gatePassed: boolean;
  gateReason: string;
}

export interface Compare {
  columns: CompareColumn[];
  pairs: PairSimilarity[];
  summary: CompareSummary;
}

export interface Health {
  storefront: "ok";
  graphrec: string;
  graphrecBaseUrl: string;
  proofConfigured: boolean;
  proofVersionId: string | null;
  catalogProducts: number | null;
  correlationId: string | null;
}

export interface Envelope<T> {
  data: T;
  meta: Record<string, unknown>;
}
