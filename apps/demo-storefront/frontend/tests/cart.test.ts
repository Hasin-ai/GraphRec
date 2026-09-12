import { describe, expect, it } from "vitest";
import { addLine, cartCount, cartProductIds, cartSubtotal, changeQty, removeLine, type CartLine } from "../src/lib/cart";
import type { Product } from "../src/lib/types";

const product = (id: string, price: string): Product => ({ externalId: id, title: id, description: null, price, category: "skincare", isActive: true, availabilityStatus: "available", available: true, brand: null, size: null, tags: [], accent: null });

describe("cart", () => {
  it("adds, merges, changes and removes lines", () => {
    let lines: CartLine[] = [];
    lines = addLine(lines, product("a", "10.00"), 1);
    lines = addLine(lines, product("a", "10.00"), 2);
    lines = addLine(lines, product("b", "2.50"), 1);
    expect(lines.map((l) => [l.product.externalId, l.qty])).toEqual([["a", 3], ["b", 1]]);
    expect(cartCount(lines)).toBe(4);
    expect(cartSubtotal(lines)).toBeCloseTo(32.5);
    expect(cartProductIds(lines)).toEqual(["a", "b"]);
    lines = changeQty(lines, "b", -1); // drops to zero -> removed
    expect(cartProductIds(lines)).toEqual(["a"]);
    lines = removeLine(lines, "a");
    expect(lines).toEqual([]);
  });

  it("caps quantities at 99", () => {
    const lines = addLine([], product("a", "1.00"), 500);
    expect(lines[0].qty).toBe(99);
  });
});
