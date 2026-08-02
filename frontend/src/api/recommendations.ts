import { GraphRecApiError } from "./types";

export interface RecommendationRequest {
  user_id?: string;
  top_n?: number;
  context?: Record<string, unknown>;
}

export interface RecommendationItem {
  external_product_id: string;
  position: number;
}

export interface RecommendationResponse {
  request_id: string;
  items: RecommendationItem[];
  model_version_id: string | null;
  strategy: string;
  fallback_used: boolean;
  fallback_tier: string;
}

export async function getRecommendations(
  apiKey: string,
  payload: RecommendationRequest,
): Promise<RecommendationResponse> {
  const res = await fetch("/v1/recommendations", {
    method: "POST",
    headers: {
      Authorization: `ApiKey ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as RecommendationResponse;
}
