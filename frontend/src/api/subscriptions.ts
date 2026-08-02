import { GraphRecApiError, type SubscriptionResult } from "./types";

export async function getSubscription(accessToken: string): Promise<SubscriptionResult> {
  const response = await fetch("/v1/subscription", {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
  });
  const body = (await response.json()) as SubscriptionResult | { error?: object };
  if (!response.ok) {
    throw new GraphRecApiError(
      response.status,
      body as ConstructorParameters<typeof GraphRecApiError>[1],
      response.headers.get("X-Correlation-ID") ?? undefined,
    );
  }
  return body as SubscriptionResult;
}
