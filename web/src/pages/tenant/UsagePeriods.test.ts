import { describe, expect, it } from "vitest";
import { recentPeriods } from "./UsagePage";

describe("UC-24 usage periods", () => {
  it("lists the current UTC month first and eleven earlier months, crossing the year", () => {
    const periods = recentPeriods(new Date(Date.UTC(2026, 1, 10)));
    expect(periods).toHaveLength(12);
    expect(periods[0]).toEqual({ value: "2026-02", label: "This period" });
    expect(periods[1].value).toBe("2026-01");
    expect(periods[2].value).toBe("2025-12");
  });
});
