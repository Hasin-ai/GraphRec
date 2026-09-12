/**
 * Identifier helpers.
 *
 * GraphRec deduplicates events and feedback by the tenant-supplied `event_id`
 * (max 100 characters). Random IDs are fine for fire-and-forget tracking; use
 * `deterministicId` when the same business fact may be sent more than once
 * (order webhooks, replayed exports) so GraphRec records it exactly once.
 */
import { createHash, randomUUID } from "node:crypto";
import { MAX_EVENT_ID_LENGTH } from "./constants.js";

/** Random unique identifier, e.g. `evt_1f0c…`. */
export function newId(prefix = ""): string {
  const token = randomUUID().replace(/-/g, "");
  return prefix ? `${prefix}_${token}` : token;
}

export function newIdempotencyKey(): string {
  return randomUUID();
}

/**
 * Stable identifier derived from `parts` (same algorithm as the Python SDK, so
 * both SDKs produce identical IDs for identical inputs).
 *
 *     deterministicId("purchase", orderId, line, { prefix: "evt" })
 */
export function deterministicId(...args: [...parts: unknown[], options: { prefix?: string }] | unknown[]): string {
  let parts = args as unknown[];
  let prefix = "";
  const last = parts[parts.length - 1];
  if (last && typeof last === "object" && !Array.isArray(last) && "prefix" in (last as object)) {
    prefix = String((last as { prefix?: string }).prefix ?? "");
    parts = parts.slice(0, -1);
  }
  if (!parts.length) throw new RangeError("deterministicId() needs at least one part");
  const material = parts.map((part) => stringify(part)).join("\x1f");
  const token = createHash("sha256").update(material, "utf8").digest("hex").slice(0, 40);
  const result = prefix ? `${prefix}_${token}` : token;
  return result.slice(0, MAX_EVENT_ID_LENGTH);
}

/** Matches Python's `str()` for the value kinds the helpers accept. */
function stringify(part: unknown): string {
  if (part === null || part === undefined) return "None";
  if (typeof part === "boolean") return part ? "True" : "False";
  return String(part);
}
