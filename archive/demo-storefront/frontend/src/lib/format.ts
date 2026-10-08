/** Formatting and the CSS-generated product art from the design canvas. */
import type { CSSProperties } from "react";

export const CATEGORY_LABEL: Record<string, string> = { skincare: "Skin", haircare: "Hair", makeup: "Makeup", fragrance: "Fragrance" };
export const CATEGORIES = ["skincare", "haircare", "makeup", "fragrance"] as const;

export function categoryLabel(category: string): string {
  return CATEGORY_LABEL[category] ?? category;
}

export function money(value: string | number): string {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? `$${n.toFixed(2)}` : String(value);
}

/** FNV-1a in [0,1): stable per id, so the same product always gets the same composition. */
export function hash(str: string): number {
  let x = 2166136261;
  for (let i = 0; i < str.length; i += 1) {
    x ^= str.charCodeAt(i);
    x = Math.imul(x, 16777619);
  }
  return (x >>> 0) / 4294967296;
}

const RAMP: Record<string, [string, string]> = {
  skincare: ["#E9EFE7", "#C9D8CD"],
  haircare: ["#F2E8DD", "#DCC9B4"],
  makeup: ["#F7E7E2", "#E8C4B8"],
  fragrance: ["#F5EEDE", "#E4D4AF"],
};
const TINT: Record<string, string> = { skincare: "#174A3A", haircare: "#8C6239", makeup: "#C0715F", fragrance: "#9A6A20" };

export function tileStyle(id: string, category: string, accent?: string | null): CSSProperties {
  const ramp = RAMP[category] ?? ["#EFEBE2", accent ?? "#D8D6CE"];
  const angle = 120 + Math.floor(hash(id) * 80);
  return { background: `linear-gradient(${angle}deg, ${ramp[0]} 0%, ${ramp[1]} 100%)` };
}

export function blobStyle(id: string, category: string): CSSProperties {
  const x = 12 + hash(id + "x") * 40;
  const y = 16 + hash(id + "y") * 34;
  const s = 40 + hash(id + "s") * 24;
  const tint = TINT[category] ?? "#647069";
  return { left: `${x.toFixed(1)}%`, top: `${y.toFixed(1)}%`, width: `${s.toFixed(1)}%`, background: `color-mix(in srgb, ${tint} 16%, transparent)` };
}

export function swatchStyle(category: string, size: number, accent?: string | null): CSSProperties {
  return { width: size, height: size, background: accent ?? RAMP[category]?.[1] ?? "#D8D6CE" };
}

export function shortId(id: string | null | undefined, length = 8): string {
  if (!id) return "—";
  return id.length > length + 1 ? `${id.slice(0, length)}…` : id;
}
