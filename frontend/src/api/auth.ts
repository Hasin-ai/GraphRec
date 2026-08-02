import { GraphRecApiError, type AuthTokenPair, type LoginInput } from "./types";

export async function login(input: LoginInput): Promise<AuthTokenPair> {
  const response = await fetch("/v1/auth/login", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });

  const body = (await response.json()) as AuthTokenPair | { error?: object };
  if (!response.ok) {
    throw new GraphRecApiError(
      response.status,
      body as ConstructorParameters<typeof GraphRecApiError>[1],
      response.headers.get("X-Correlation-ID") ?? undefined,
    );
  }
  return body as AuthTokenPair;
}

export async function setupPassword(input: LoginInput): Promise<AuthTokenPair> {
  const response = await fetch("/v1/auth/setup-password", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });

  const body = (await response.json()) as AuthTokenPair | { error?: object };
  if (!response.ok) {
    throw new GraphRecApiError(
      response.status,
      body as ConstructorParameters<typeof GraphRecApiError>[1],
      response.headers.get("X-Correlation-ID") ?? undefined,
    );
  }
  return body as AuthTokenPair;
}
