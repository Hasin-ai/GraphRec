/**
 * Plan limits shown on the public site. The single frontend source for /pricing
 * and the landing-page teaser.
 *
 * Mirrors the seeded rows in `pricing_plans`:
 *   - migrations/versions/0001_registration_slice.py   (Free)
 *   - migrations/versions/0012_basic_pro_plans.py       (Basic, Pro)
 *   - migrations/versions/0031_free_plan_serving_limits.py (Free serving limits: 8 concurrent, 120 rpm, 1 replica)
 *
 * A platform operator can edit plans at runtime (/admin/plans), so these
 * numbers are the seeded defaults, not a live read. There is no public plans
 * endpoint (GET /v1/platform/plans needs the operator token). Plans carry no
 * prices; every tenant starts on Free and only an operator assigns Basic or Pro.
 */
import { fmtBytes, fmtNumber } from "../lib/format";
import { humanizeKey } from "../lib/labels";

/** Keys identical to the backend `limits` JSON, in display order. */
export const LIMIT_KEYS = [
  "accepted_events",
  "recommendation_requests",
  "requests_per_minute",
  "concurrent_recommendation_requests",
  "stored_products",
  "training_jobs",
  "concurrent_training_jobs",
  "maximum_training_duration_minutes",
  "active_model_versions",
  "maximum_inference_replicas",
  "artifact_storage_bytes",
  "queued_messages",
] as const;
export type LimitKey = (typeof LIMIT_KEYS)[number];

/** Counters that reset at the start of each calendar month (UTC); the rest are standing totals or rates. */
export const MONTHLY_LIMITS: ReadonlySet<LimitKey> = new Set<LimitKey>(["accepted_events", "recommendation_requests", "training_jobs"]);

export type PlanCode = "free" | "basic" | "pro";
export interface MarketingPlan {
  code: PlanCode;
  name: string;
  tagline: string;
  limits: Record<LimitKey, number>;
  /** Plans carry no prices and payments are out of scope. */
  price: null;
}

const GIB = 1024 ** 3;

export const PLANS: MarketingPlan[] = [
  {
    code: "free",
    name: "Free",
    tagline: "For evaluating GraphRec on a real catalog.",
    price: null,
    limits: {
      accepted_events: 50_000,
      recommendation_requests: 20_000,
      requests_per_minute: 120,
      concurrent_recommendation_requests: 8,
      stored_products: 5_000,
      training_jobs: 1,
      concurrent_training_jobs: 1,
      maximum_training_duration_minutes: 30,
      active_model_versions: 2,
      maximum_inference_replicas: 1,
      artifact_storage_bytes: 1 * GIB,
      queued_messages: 500,
    },
  },
  {
    code: "basic",
    name: "Basic",
    tagline: "For a live shop that retrains every week.",
    price: null,
    limits: {
      accepted_events: 500_000,
      recommendation_requests: 250_000,
      requests_per_minute: 300,
      concurrent_recommendation_requests: 12,
      stored_products: 50_000,
      training_jobs: 4,
      concurrent_training_jobs: 1,
      maximum_training_duration_minutes: 60,
      active_model_versions: 5,
      maximum_inference_replicas: 2,
      artifact_storage_bytes: 5 * GIB,
      queued_messages: 5_000,
    },
  },
  {
    code: "pro",
    name: "Pro",
    tagline: "For large catalogs and frequent retraining.",
    price: null,
    limits: {
      accepted_events: 2_000_000,
      recommendation_requests: 1_000_000,
      requests_per_minute: 1_000,
      concurrent_recommendation_requests: 30,
      stored_products: 500_000,
      training_jobs: 12,
      concurrent_training_jobs: 2,
      maximum_training_duration_minutes: 180,
      active_model_versions: 10,
      maximum_inference_replicas: 3,
      artifact_storage_bytes: 20 * GIB,
      queued_messages: 50_000,
    },
  },
];

/** The three limits a plan card leads with. */
export const HEADLINE_LIMITS: LimitKey[] = ["accepted_events", "recommendation_requests", "stored_products"];

/** Row label, from lib/labels.ts so /pricing uses the same words as /usage and /admin/plans. */
export function limitLabel(key: LimitKey): string {
  return humanizeKey(key);
}

/** "50,000", "1.0 GB": the console's own number and byte formatters. */
export function formatLimit(key: LimitKey, value: number): string {
  return key === "artifact_storage_bytes" ? fmtBytes(value) : fmtNumber(value);
}
