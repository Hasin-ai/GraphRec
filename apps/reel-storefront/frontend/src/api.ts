import type { Film, FilmPage, Genre, ProofReport, Receipt, Recs, Sequence, Session, SortKey, Status, Tag, Unavailable } from "./types";

export class ApiError extends Error {
  constructor(public code: string, message: string, public correlationId?: string) { super(message); }
}

async function call<T>(path: string, init?: RequestInit): Promise<{ data: T; meta: Record<string, unknown> }> {
  const res = await fetch(`/api/reel${path}`, {
    credentials: "same-origin",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const e = body.error ?? {};
    throw new ApiError(e.code ?? "http_error", e.message ?? `Request failed (${res.status})`, e.correlationId);
  }
  return body;
}

const post = <T,>(path: string, json?: unknown) => call<T>(path, { method: "POST", body: JSON.stringify(json ?? {}) });

export const api = {
  session: () => call<Session>("/session").then((r) => r.data),
  resetGuest: () => post<Session>("/session/reset").then((r) => r.data),
  setPersona: (persona: string, carrySession = false) =>
    post<Session>("/session/persona", { persona, carrySession }).then((r) => ({ session: r.data, carried: (r.meta.carried ?? []) as Receipt[] })),
  genres: () => call<Genre[]>("/genres").then((r) => r.data),
  tags: (limit = 40) => call<Tag[]>(`/tags?limit=${limit}`).then((r) => r.data),
  films: (p: { genre?: string; tag?: string; q?: string; sort?: SortKey; offset?: number; limit?: number }) => {
    const qs = new URLSearchParams();
    Object.entries(p).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
    return call<FilmPage>(`/films?${qs}`).then((r) => r.data);
  },
  film: (id: string) => call<Film>(`/films/${encodeURIComponent(id)}`).then((r) => r.data),
  watch: (filmId: string, from?: { requestId: string; position: number }) =>
    post<Receipt>("/watch", { filmId, ...(from ?? {}) }).then((r) => r.data),
  replay: () => post<Receipt>("/watch/replay").then((r) => r.data),
  recommend: (shelf: "home" | "more_like", filmId?: string, opts?: { diversity?: number }) =>
    post<Recs | Unavailable>("/recommendations", { shelf, filmId, ...(opts ?? {}) }).then((r) => r.data),
  click: (requestId: string, filmId: string, position: number) => post("/feedback/click", { requestId, filmId, position }),
  history: () => call<Film[]>("/insight/history").then((r) => r.data),
  sequence: () => call<Sequence>("/insight/sequence").then((r) => r.data),
  status: () => call<Status>("/insight/status").then((r) => r.data),
  proofLatest: () => call<ProofReport | null>("/proof/latest").then((r) => r.data),
  proofRun: (profile = "full") => post<ProofReport>("/proof/run", { profile }).then((r) => r.data),
};

export const isUnavailable = (r: Recs | Unavailable): r is Unavailable => (r as Unavailable).available === false;
