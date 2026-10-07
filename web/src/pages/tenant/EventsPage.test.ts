import { describe, expect, it } from "vitest";
import { GraphRecApiError } from "../../api/types";
import { mapError } from "./EventsPage";

describe("Events page error mapping (D14)", () => {
  it("shows the validation message for a product outside this tenant's catalog", () => {
    const error = new GraphRecApiError(422, { error: { code: "invalid_product_reference", message: "The event product does not exist in this tenant catalog." } });
    const mapped = mapError(error);
    expect(mapped.body).toBe("The event product does not exist in this tenant catalog.");
    expect(mapped.title).toBe("The submission cannot be accepted");
  });
  it("keeps the retry advice for server errors", () => {
    expect(mapError(new GraphRecApiError(503, { error: { code: "service_unavailable", message: "x" } })).body).toBe("Try again shortly.");
  });
});
