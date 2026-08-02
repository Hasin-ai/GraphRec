import { GraphRecApiError, type UsageSummaryResult } from "./types";

export async function getUsage(accessToken: string): Promise<UsageSummaryResult> {
  const response = await fetch("/v1/usage", {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
  });
  const body = (await response.json()) as UsageSummaryResult | { error?: object };
  if (!response.ok) {
    throw new GraphRecApiError(
      response.status,
      body as ConstructorParameters<typeof GraphRecApiError>[1],
      response.headers.get("X-Correlation-ID") ?? undefined,
    );
  }
  return body as UsageSummaryResult;
}
