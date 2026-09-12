import type { GraphRec } from "../client.js";

export abstract class Resource {
  protected readonly client: GraphRec;
  constructor(client: GraphRec) {
    this.client = client;
  }
}

export function toIso(value: string | Date | undefined | null): string | undefined {
  if (value === undefined || value === null) return undefined;
  return value instanceof Date ? value.toISOString() : value;
}

export function utcNow(): string {
  return new Date().toISOString();
}

/** Drop `undefined` values so they are omitted from the JSON body. */
export function compact<T extends Record<string, unknown>>(value: T): Partial<T> {
  const out: Record<string, unknown> = {};
  for (const [key, v] of Object.entries(value)) if (v !== undefined) out[key] = v;
  return out as Partial<T>;
}
