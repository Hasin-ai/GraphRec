import {
  GraphRecApiError,
  type TenantRegistrationInput,
  type TenantRegistrationResult,
} from "./types";

export async function registerTenant(
  input: TenantRegistrationInput,
  idempotencyKey: string,
): Promise<TenantRegistrationResult> {
  const response = await fetch("/v1/tenants", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(input),
  });

  const body = (await response.json()) as TenantRegistrationResult | { error?: object };
  if (!response.ok) {
    throw new GraphRecApiError(
      response.status,
      body as ConstructorParameters<typeof GraphRecApiError>[1],
      response.headers.get("X-Correlation-ID") ?? undefined,
    );
  }
  return body as TenantRegistrationResult;
}
