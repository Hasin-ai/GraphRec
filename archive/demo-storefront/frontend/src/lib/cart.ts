/** Cart state in localStorage, one namespace per persona. Durability is not part of the proof. */
import type { Product } from "./types";

export interface CartLine {
  product: Product;
  qty: number;
}

const KEY = (persona: string) => `facet:cart:${persona}`;

export function loadCart(persona: string): CartLine[] {
  try {
    const raw = localStorage.getItem(KEY(persona));
    const parsed = raw ? (JSON.parse(raw) as CartLine[]) : [];
    return Array.isArray(parsed) ? parsed.filter((l) => l && l.product && l.qty > 0) : [];
  } catch {
    return [];
  }
}

export function saveCart(persona: string, lines: CartLine[]): void {
  try {
    localStorage.setItem(KEY(persona), JSON.stringify(lines));
  } catch {
    /* storage unavailable: the cart is still usable for this page load */
  }
}

export function addLine(lines: CartLine[], product: Product, qty: number): CartLine[] {
  const existing = lines.find((l) => l.product.externalId === product.externalId);
  if (existing) return lines.map((l) => (l === existing ? { ...l, qty: Math.min(99, l.qty + qty) } : l));
  return [...lines, { product, qty: Math.min(99, Math.max(1, qty)) }];
}

export function changeQty(lines: CartLine[], productId: string, delta: number): CartLine[] {
  return lines.map((l) => (l.product.externalId === productId ? { ...l, qty: l.qty + delta } : l)).filter((l) => l.qty > 0);
}

export function removeLine(lines: CartLine[], productId: string): CartLine[] {
  return lines.filter((l) => l.product.externalId !== productId);
}

export function cartCount(lines: CartLine[]): number {
  return lines.reduce((s, l) => s + l.qty, 0);
}

export function cartSubtotal(lines: CartLine[]): number {
  return lines.reduce((s, l) => s + Number(l.product.price) * l.qty, 0);
}

export function cartProductIds(lines: CartLine[]): string[] {
  return lines.map((l) => l.product.externalId);
}

/** A stable key for one checkout attempt, so a retried request yields the same order and events. */
export function newOrderKey(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
