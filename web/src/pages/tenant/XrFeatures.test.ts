import { describe, expect, it } from "vitest";
import { parseWeight } from "./RecommendationRulesPage";
import { parseBounded } from "./RetrainingPolicyPanel";
import { rangeError } from "./UsageTrends";

describe("XR feature form validation", () => {
  it("accepts only whole numbers inside the bounds", () => {
    expect(parseBounded("60", 60, 43200)).toBe(60);
    expect(parseBounded("59", 60, 43200)).toMatch(/from 60/);
    expect(parseBounded("1.5", 1, 10)).toMatch(/whole number/);
    expect(parseBounded("", 1, 10)).toMatch(/whole number/);
    expect(parseBounded("9".repeat(400), 1, 10)).toMatch(/from 1/);
  });
  it("bounds the freshness weight to 0..0.3", () => {
    expect(parseWeight("0.3")).toBe(0.3);
    expect(parseWeight("0.31")).toMatch(/0 to 0.3/);
    expect(parseWeight("abc")).toMatch(/number/);
  });
  it("validates trend ranges per granularity", () => {
    expect(rangeError("2026-09-01", "2026-09-30", "day")).toBeNull();
    expect(rangeError("2026-09-30", "2026-09-01", "day")).toMatch(/end date/);
    expect(rangeError("2026-08-01", "2026-09-30", "hour")).toMatch(/31 days/);
    expect(rangeError("09/01/2026", "2026-09-30", "day")).toMatch(/YYYY-MM-DD/);
  });
});
