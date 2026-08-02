import type { AuthTokenPair } from "../api/types";

let activeSession: AuthTokenPair | null = null;

export function getAuthSession(): AuthTokenPair | null {
  return activeSession;
}

export function setAuthSession(session: AuthTokenPair): void {
  activeSession = session;
}

export function clearAuthSession(): void {
  activeSession = null;
}
