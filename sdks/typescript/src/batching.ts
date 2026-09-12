/**
 * Byte-budget chunking for bulk endpoints.
 *
 * GraphRec rejects request bodies above `MAX_REQUEST_BODY_BYTES` (16 KiB by
 * default) with `413 payload_too_large`. Bulk helpers split their input so that
 * every request fits, measuring each item with the exact encoder used to send it.
 */
import { InputValidationError } from "./errors.js";

/** Compact JSON, identical to what the transport sends. */
export function encodeJson(value: unknown): string {
  return JSON.stringify(value);
}

export function byteLength(text: string): number {
  return Buffer.byteLength(text, "utf8");
}

export interface ChunkOptions {
  envelopeKey: string;
  maxBytes: number;
  maxItems: number;
  describe?: string;
}

/** Split JSON-ready `items` so each `{[envelopeKey]: [...]}` body fits `maxBytes`. */
export function chunkItems<T>(items: readonly T[], options: ChunkOptions): T[][] {
  const { envelopeKey, maxBytes, maxItems, describe = "item" } = options;
  const overhead = byteLength(encodeJson({ [envelopeKey]: [] }));
  const chunks: T[][] = [];
  let current: T[] = [];
  let currentSize = overhead;

  for (const item of items) {
    const size = byteLength(encodeJson(item));
    if (overhead + size > maxBytes) {
      const record = item as { external_id?: unknown; event_id?: unknown } | null;
      const label = record && typeof record === "object" ? (record.external_id ?? record.event_id) : undefined;
      throw new InputValidationError(
        `${describe} ${JSON.stringify(label)} encodes to ${size} bytes, which cannot fit in a ${maxBytes}-byte request. ` +
          "Shrink it (e.g. its metadata/context) or raise maxBodyBytes to match the server's MAX_REQUEST_BODY_BYTES.",
      );
    }
    let added = size + (current.length ? 1 : 0);
    if (current.length && (currentSize + added > maxBytes || current.length >= maxItems)) {
      chunks.push(current);
      current = [];
      currentSize = overhead;
      added = size;
    }
    current.push(item);
    currentSize += added;
  }
  if (current.length) chunks.push(current);
  return chunks;
}
