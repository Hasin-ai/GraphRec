import { describe, expect, it } from "vitest";
import { proofPillLabel, proofTone, provenanceLine, shelfHeading, whyRows } from "../src/lib/proof";
import type { Provenance } from "../src/lib/types";

const base: Provenance = {
  requestId: "rec_1",
  modelVersionId: "a93f251e-80cb-48c2-8789-7a8d98e10aac",
  rawStrategy: "personalized",
  fallbackUsed: false,
  fallbackTier: "none",
  proofStatus: "serving_preview",
  excludedCount: 2,
  omittedProductCount: 0,
  impressionEventId: "imp_1",
};

describe("honesty gate wording", () => {
  it("never claims personalisation from the raw strategy alone", () => {
    // The backend says "personalized" but the proof status is preview.
    expect(shelfHeading("serving_preview", "Maya", "home")).toBe("Recommended");
    expect(provenanceLine(base, "Maya", false)).toBe("GraphRec serving preview · version a93f251e · showing as Maya");
    expect(proofPillLabel("serving_preview")).toBe("Serving preview · unverified");
    expect(proofTone("serving_preview")).toBe("preview");
  });

  it("uses 'For <name>' and 'Model-backed' only when verified", () => {
    expect(shelfHeading("model_verified", "Maya", "home")).toBe("For Maya");
    expect(provenanceLine({ ...base, proofStatus: "model_verified" }, "Maya", false)).toBe("Model-backed for Maya · version a93f251e");
    expect(proofTone("model_verified")).toBe("verified");
  });

  it("labels fallbacks as catalog fallbacks and never as popular", () => {
    const fallback: Provenance = { ...base, proofStatus: "catalog_fallback", fallbackUsed: true, fallbackTier: "tenant_popular", modelVersionId: null, rawStrategy: "popular_fallback" };
    expect(shelfHeading("catalog_fallback", "New visitor", "home")).toBe("From the catalog");
    expect(provenanceLine(fallback, "New visitor", true)).toBe("Catalog fallback · new visitor, no history");
    expect(provenanceLine(fallback, "Maya", false)).toBe("Catalog fallback · showing as Maya");
    for (const text of [shelfHeading("catalog_fallback", "x", "home"), provenanceLine(fallback, "x", true), proofPillLabel("catalog_fallback")]) {
      expect(text.toLowerCase()).not.toContain("popular");
      expect(text.toLowerCase()).not.toContain("personal");
    }
  });

  it("shows the raw strategy only in the disclosure, explicitly labelled raw", () => {
    const rows = whyRows(base);
    expect(rows.find((r) => r.label.startsWith("Raw strategy"))?.value).toBe("personalized");
    expect(rows.map((r) => r.label)).toContain("Proof status");
    expect(shelfHeading(null, "Maya", "home")).toBe("Recommended");
  });
});
