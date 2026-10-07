import type { ModelVersionResource, TrainingJobResource } from "../api/types";
import { humanize } from "./format";

/** "dgsr" -> "DGSR", "item_knn" -> "Item knn". Short lowercase codes read as acronyms. */
export function modelTypeLabel(type: string | null | undefined): string {
  if (!type) return "Model";
  return /^[a-z]{2,5}$/.test(type) ? type.toUpperCase() : humanize(type);
}

/** "DGSR model · v3" — ordinal by creation among the given versions. */
export function modelLabel(model: Pick<ModelVersionResource, "id" | "model_type" | "created_at">, all: Pick<ModelVersionResource, "id" | "created_at">[]): string {
  const ordered = all.slice().sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
  const n = ordered.findIndex((v) => v.id === model.id) + 1;
  return `${modelTypeLabel(model.model_type)} model${n ? ` · v${n}` : ""}`;
}

/** "Training run #4" — ordinal by request time among the given jobs. */
export function jobLabel(job: Pick<TrainingJobResource, "id" | "created_at">, all: Pick<TrainingJobResource, "id" | "created_at">[]): string {
  const ordered = all.slice().sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
  const n = ordered.findIndex((j) => j.id === job.id) + 1;
  return n ? `Training run #${n}` : "Training run";
}

/** "validation.NDCG@10" -> "NDCG@10 (validation)". */
export function metricLabel(key: string): string {
  const parts = key.split(".");
  const last = parts.pop() ?? key;
  const scope = parts.join(" ");
  return scope ? `${last} (${scope.replace(/_/g, " ")})` : last;
}

/** True for identifiers/codes worth a monospace face; false for prose, dates, plain numbers. */
export function isCodeLike(value: unknown): boolean {
  if (typeof value !== "string") return false;
  const v = value.trim();
  if (!v || /\s/.test(v)) return false;
  if (/^[\d.,]+%?$/.test(v)) return false;
  return true;
}

// ── shared human-friendly helpers (audit X-4, X-10, X-14) ─────────────────

const KEY_LABELS: Record<string, string> = {
  items: "Items", users: "Users", layers: "Layers", artifact: "Checkpoint", interactions: "Interactions",
  embedding_dim: "Embedding size", indexed_items: "Indexed items", engine_version: "Engine version",
  checkpoint_epoch: "Checkpoint epoch", data_fingerprint: "Data fingerprint", selection_ndcg10: "Selection NDCG@10",
  checkpoint_sha256: "Checkpoint hash", event_user_coverage: "User coverage", catalog_item_coverage: "Catalog coverage",
  evaluated_examples: "Evaluated examples", mode: "Mode", pretrained_artifact: "Checkpoint", epochs: "Epochs",
  training_jobs: "Training jobs", accepted_events: "Accepted events", stored_products: "Stored products",
  recommendation_requests: "Recommendation requests", active_model_versions: "Active model versions",
  artifact_storage_bytes: "Model storage", training_cpu_seconds: "Training compute", inference_replicas: "Serving replicas",
  replica_runtime_minutes: "Serving runtime", queued_messages: "Queued messages", requests_per_minute: "Requests per minute",
  concurrent_training_jobs: "Concurrent training jobs", maximum_inference_replicas: "Maximum serving replicas",
  maximum_training_duration_minutes: "Maximum training duration (min)", concurrent_recommendation_requests: "Concurrent recommendation requests",
};

/** True when `key` has a curated label (the pricing page asserts every plan limit does). */
export function hasKeyLabel(key: string): boolean {
  return Object.prototype.hasOwnProperty.call(KEY_LABELS, key);
}

/** "embedding_dim" -> "Embedding size"; unknown snake_case keys are sentence-cased. Ranking keys (Hit@5) pass through. */
export function humanizeKey(key: string): string {
  const last = key.split(".").pop() ?? key;
  if (KEY_LABELS[last]) return KEY_LABELS[last];
  if (/@\d+$/.test(last)) return last;
  const words = last.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const INTEGER_KEYS = /(^|\.)(items|users|layers|interactions|embedding_dim|indexed_items|checkpoint_epoch|evaluated_examples)$/;
/** Integers never print as floats ("57289.0000" -> "57,289"); scores keep 3–4 decimals; coverage reads as a percent. */
export function formatMetricValue(key: string, value: unknown): string {
  if (typeof value !== "number") return String(value ?? "—");
  if (INTEGER_KEYS.test(key) || Number.isInteger(value) && Math.abs(value) >= 2) return Math.round(value).toLocaleString("en-US");
  if (/coverage$/.test(key)) return `${(value * 100).toFixed(value === 1 ? 0 : 1)}%`;
  return value.toFixed(4);
}

/** "sampled_101" -> a sentence a non-specialist can read. */
export function evaluationModeLabel(mode: unknown): string {
  if (typeof mode !== "string") return "Not recorded";
  const sampled = /^sampled_(\d+)$/.exec(mode);
  if (sampled) return `Sampled: each test user's true next item ranked against ${Number(sampled[1]) - 1} random items`;
  if (mode === "full") return "Full catalog ranking";
  return humanizeKey(mode);
}

/** Natural ordering: "Item 2" before "Item 10". */
const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
export const naturalCompare = (a: string, b: string) => collator.compare(a, b);

/** Whole days since a timestamp, rounded the same way everywhere ("21 days ago"). */
export function daysSince(value: string | number | null | undefined, now = Date.now()): number | null {
  if (value === null || value === undefined) return null;
  const t = new Date(value).getTime();
  return Number.isNaN(t) ? null : Math.round((now - t) / 86_400_000);
}
export function daysAgoLabel(value: string | number | null | undefined): string {
  const d = daysSince(value);
  return d === null ? "—" : d <= 0 ? "today" : d === 1 ? "yesterday" : `${d} days ago`;
}

/** What each lifecycle status means, for badge tooltips and legends (audit X-5). */
export const STATUS_HELP: Record<string, Record<string, string>> = {
  model: {
    eligible: "Available: trained and evaluated, never served. Activate it to serve.",
    active: "Serving: this version answers every recommendation request.",
    retired: "Available: served before. Roll back to serve it again.",
    archived: "Kept for audit only. Can't serve or be rolled back to.",
  },
  job: {
    queued: "Waiting for a worker.", running: "In progress.", succeeded: "Finished and registered a model version.",
    failed: "Stopped before producing a version.", cancelled: "Cancelled before finishing.", cancelling: "Cancellation requested.",
  },
  deploy: { available: "A model is loaded and can answer requests.", stopped: "No model is serving." },
  key: { active: "Can authenticate requests.", expired: "Past its expiry date; refused.", revoked: "Revoked; refused." },
};

const USAGE_LABELS: Record<string, string> = {
  accepted_events: "Accepted events", recommendation_requests: "Recommendation requests", training_jobs: "Training jobs",
  training_cpu_seconds: "Training CPU seconds", stored_products: "Stored products", artifact_storage_bytes: "Artifact storage",
  active_model_versions: "Active model versions", inference_replicas: "Inference replicas", replica_runtime_minutes: "Replica runtime",
};
/** Usage dimension label with correct casing ("training_cpu_seconds" -> "Training CPU seconds"). */
export function usageLabel(type: string): string {
  return USAGE_LABELS[type] ?? humanize(type).replace(/ bytes$/, "");
}
