import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CommonComparison, comparisonOf } from "./CommonComparison";

const scores = (ndcg: number) => ({ examples: 40, "Hit@1": 0.1, "Hit@10": 0.5, "NDCG@10": ndcg, "MRR@10": 0.2, "catalog_coverage@10": 0.3, unknown_targets: 0 });

describe("XR-F-10 common-set comparison", () => {
  it("shows candidate, active and baseline on the same examples with the difference", () => {
    const comparison = comparisonOf({ comparison: { protocol: "p", examples: 40, candidate: scores(0.4), popularity_baseline: scores(0.1), active: { model_version_id: "v1", ...scores(0.3) } } })!;
    render(<CommonComparison comparison={comparison} activeLabel="trained-1" />);
    expect(screen.getByText("Active then (trained-1)")).toBeInTheDocument();
    expect(screen.getByText("+0.1000")).toBeInTheDocument();
  });
  it("says when the active version could not be scored instead of inventing numbers", () => {
    const comparison = comparisonOf({ comparison: { protocol: "p", examples: 40, candidate: scores(0.4), popularity_baseline: scores(0.1), active: { model_version_id: "v1", unavailable_reason: "ArtifactError: missing" } } })!;
    render(<CommonComparison comparison={comparison} />);
    expect(screen.getByText("The active version could not be scored")).toBeInTheDocument();
    expect(screen.queryByText("Difference")).toBeNull();
  });
  it("ignores versions without a comparison", () => expect(comparisonOf({ validation: {} })).toBeNull());
});
