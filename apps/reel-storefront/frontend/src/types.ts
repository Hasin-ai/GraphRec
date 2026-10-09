export interface Film {
  id: string;
  title: string;
  year: number | null;
  genres: string[];
  /** Community tags from MovieLens, most-used first. */
  tags: string[];
  popularity: number;
  popularityRank: number;
  tmdbId?: string | null;
  imdbId?: string | null;
  posterUrl?: string | null;
}
export interface FilmPage { items: Film[]; total: number; offset: number; limit: number }
export interface Genre { name: string; films: number }
export interface Tag { name: string; films: number }
export type SortKey = "popular" | "newest" | "oldest" | "title";
export interface Persona { key: string; name: string; blurb: string; color: string; userId: string | null; historyLength: number }
export interface Session { persona: Persona; sessionId: string; personas: Persona[] }
export interface Receipt { eventId: string; eventType: string; filmId: string; accepted: boolean; duplicate: boolean; latencyMs: number; feedback?: string | null }
export interface Ranked extends Film { position: number; change: "new" | "up" | "down" | "same"; previousPosition: number | null }
export interface Trace {
  request: { endpoint: string; userId: string | null; topN: number; recentProductIds: string[]; excludeCount: number };
  requestId: string; modelVersionId: string | null; strategy: string; fallbackUsed: boolean; fallbackTier: string;
  appliedRules: string[]; latencyMs: number;
}
export interface Diff { hasPrevious: boolean; entered: string[]; left: Film[]; changed: number; summary: string }
export interface Recs { shelf: "home" | "more_like"; title: string; items: Ranked[]; trace: Trace; diff: Diff; omitted: number; impression?: string | null }
export interface Unavailable { available: false; reason: string; correlationId?: string | null }
export interface SequenceItem { film: Film; time: number; origin: "training" | "live"; eventType: string; eventId: string | null; inWindow: boolean; evicted: boolean }
export interface Sequence { shopper: string; total: number; window: number; items: SequenceItem[]; liveCount: number; sessionOnly: boolean }
export interface Metric { protocol: string; source: string; hit10?: number; ndcg10?: number; recall10?: number; mrr?: number; note: string }
export interface Status {
  tenant: string; graphrec: string; modelVersionId: string | null; modelVersionTag: string | null; liveEvents: number;
  modelSource: "checkpoint" | "trained" | string;
  modelCard: null | { dataset: string; checkpointSha256: string; users: number; films: number; interactions: number; embeddingDim: number; layers: number; recentItems: number; itemNeighborLimit: number; metrics: Metric[] };
  feedbackHealth?: Record<string, { success: number; failure: number }>;
  readiness?: Record<string, string>;
}

export interface ProofCheckResult {
  id: string;
  name: string;
  passed: boolean;
  duration_ms: number;
  evidence: Record<string, unknown>;
  detail?: string | null;
}

export interface ProofBatterySummary {
  run_id: string;
  profile: string;
  started_at: string;
  completed_at: string;
  total_checks: number;
  passed_checks: number;
  failed_checks: number;
  success_rate: number;
  total_duration_ms: number;
}

export interface ProofReport {
  summary: ProofBatterySummary;
  checks: ProofCheckResult[];
}
