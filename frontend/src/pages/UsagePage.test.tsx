import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { AuthTokenPair, UsageSummaryResult } from "../api/types";
import { clearAuthSession, setAuthSession } from "../auth/session";

const adminSession: AuthTokenPair = {
  access_token: "usage-access-token",
  token_type: "Bearer",
  expires_in: 900,
  refresh_token: "usage-refresh-token",
  user_role: "tenant_administrator",
  scopes: ["usage:read", "billing:read"],
};

const dimensions: UsageSummaryResult["dimensions"] = [
  { type: "accepted_events", used: 0, limit: 50000, remaining: 50000, unit: "count" },
  { type: "recommendation_requests", used: 0, limit: 20000, remaining: 20000, unit: "count" },
  { type: "training_jobs", used: 0, limit: 1, remaining: 1, unit: "count" },
  { type: "training_cpu_seconds", used: 0, limit: null, remaining: null, unit: "seconds" },
  { type: "stored_products", used: 0, limit: 5000, remaining: 5000, unit: "count" },
  { type: "artifact_storage_bytes", used: 0, limit: 1073741824, remaining: 1073741824, unit: "bytes" },
  { type: "active_model_versions", used: 0, limit: 2, remaining: 2, unit: "count" },
  { type: "inference_replicas", used: 0, limit: 1, remaining: 1, unit: "count" },
  { type: "replica_runtime_minutes", used: 0, limit: null, remaining: null, unit: "minutes" },
];

const zeroUsage: UsageSummaryResult = {
  period_start: "2026-08-01T00:00:00Z",
  period_end: "2026-09-01T00:00:00Z",
  reset_at: "2026-09-01T00:00:00Z",
  dimensions,
  last_reconciled_at: "2026-08-01T11:45:00Z",
  project_defaults: true,
};

beforeEach(() => {
  clearAuthSession();
  window.history.replaceState({}, "", "/app/usage");
});

afterEach(() => vi.unstubAllGlobals());

describe("UsagePage", () => {
  it("renders the complete zero state from the credential-scoped endpoint", async () => {
    setAuthSession(adminSession);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(zeroUsage), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    expect(await screen.findByText("No metered usage in this period.")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(9);
    expect(screen.getByText("Training cpu seconds")).toBeInTheDocument();
    expect(screen.getAllByText(/Informational dimension/)).toHaveLength(2);
    expect(screen.getByText("Last reconciled")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/v1/usage", {
      method: "GET",
      headers: { Accept: "application/json", Authorization: "Bearer usage-access-token" },
    });
  });

  it("renders near, exceeded, and informational dimension states", async () => {
    setAuthSession(adminSession);
    const result: UsageSummaryResult = {
      ...zeroUsage,
      dimensions: dimensions.map((item) => {
        if (item.type === "accepted_events") return { ...item, used: 45000, remaining: 5000 };
        if (item.type === "stored_products") return { ...item, used: 6000, remaining: 0 };
        if (item.type === "training_cpu_seconds") return { ...item, used: 12.5 };
        return item;
      }),
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(result), { status: 200, headers: { "Content-Type": "application/json" } }),
      ),
    );
    render(<App />);

    await screen.findByText("Current reconciled usage");
    expect(screen.getByText("Accepted events").closest("article")).toHaveClass("usage-near");
    expect(screen.getByText("Stored products").closest("article")).toHaveClass("usage-exceeded");
    expect(screen.getByText("Training cpu seconds").closest("article")).toHaveClass("usage-informational");
    expect(screen.queryByText("No metered usage in this period.")).not.toBeInTheDocument();
  });

  it("blocks missing usage scope without calling the API", () => {
    setAuthSession({ ...adminSession, user_role: "tenant_developer", scopes: ["catalog:read"] });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    expect(screen.getByText("Usage access is not granted.")).toBeInTheDocument();
    expect(screen.getByText(/usage:read/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps last successful totals visible when reconciliation is delayed", async () => {
    setAuthSession(adminSession);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(zeroUsage), { status: 200, headers: { "Content-Type": "application/json" } }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: "metrics_unavailable",
              message: "Usage information is temporarily unavailable",
              correlation_id: "cb8fbc7b-daba-4bc3-b847-54658776a94a",
              retryable: true,
              retry_after_seconds: 5,
            },
          }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await screen.findByText("No metered usage in this period.");
    await userEvent.setup().click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("last successful totals remain visible");
    expect(screen.getByText("No metered usage in this period.")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("clears an expired session and returns to login with usage context", async () => {
    setAuthSession(adminSession);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: "token_expired", message: "Access token expired", retryable: false } }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    render(<App />);

    expect(await screen.findByText("Your session expired. Sign in again to continue.")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/auth/login");
    expect(window.location.search).toContain("returnTo=%2Fapp%2Fusage");
  });
});
