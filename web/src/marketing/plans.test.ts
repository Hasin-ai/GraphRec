import { describe, expect, it } from "vitest";
import { PLANS, mergeLivePlans } from "./plans";

describe("live plan limits (A-25)", () => {
  it("flags seeded defaults as not live", () => {
    expect(mergeLivePlans(null)).toEqual({ plans: PLANS, live: false });
  });
  it("uses the operator's current limits and names", () => {
    const { plans, live } = mergeLivePlans([{ code: "basic", name: "Basic+", limits: { stored_products: 1234 } }]);
    expect(live).toBe(true);
    expect(plans.map(p => p.code)).toEqual(["basic"]);
    expect(plans[0].name).toBe("Basic+");
    expect(plans[0].limits.stored_products).toBe(1234);
  });
});
