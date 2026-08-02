import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { AuthTokenPair } from "../api/types";
import { clearAuthSession, setAuthSession } from "../auth/session";

const adminSession: AuthTokenPair = {
  access_token: "admin-access-token",
  token_type: "Bearer",
  expires_in: 900,
  refresh_token: "admin-refresh-token",
  user_role: "tenant_administrator",
  scopes: ["billing:read", "usage:read"],
};

const subscription = {
  plan_code: "free",
  status: "active",
  period_start: "2026-08-01T00:00:00Z",
  period_end: "2026-09-01T00:00:00Z",
  limits: {
    accepted_events: 50000,
    stored_products: 5000,
    artifact_storage_bytes: 1073741824,
  },
  project_defaults: true,
};

beforeEach(() => {
  clearAuthSession();
  window.history.replaceState({}, "", "/app/subscription");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SubscriptionPage", () => {
  it("loads the credential tenant subscription and refreshes it", async () => {
    setAuthSession(adminSession);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(subscription), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    expect(await screen.findByText("Effective limits")).toBeInTheDocument();
    expect(screen.getByText("Accepted events")).toBeInTheDocument();
    expect(screen.getByText("50,000")).toBeInTheDocument();
    expect(screen.getByText("Project-default demonstration limits")).toBeInTheDocument();
    expect(screen.queryByText(/payment method/i)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/v1/subscription", {
      method: "GET",
      headers: {
        Accept: "application/json",
        Authorization: "Bearer admin-access-token",
      },
    });

    await userEvent.setup().click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("blocks accounts without billing read before making a request", () => {
    setAuthSession({
      ...adminSession,
      user_role: "tenant_developer",
      scopes: ["catalog:read"],
    });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    expect(screen.getByText("Subscription access is not granted.")).toBeInTheDocument();
    expect(screen.getByText(/billing:read/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows rate-limit retry guidance and correlation reference", async () => {
    setAuthSession(adminSession);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "rate_limit_exceeded",
              message: "Subscription read limit exceeded",
              correlation_id: "c064c53e-d447-43cc-b6e4-6148275e90b1",
              retryable: true,
              retry_after_seconds: 12,
            },
          }),
          { status: 429, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many refreshes. Try again in 12 seconds.",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Reference: c064c53e-d447-43cc-b6e4-6148275e90b1",
    );
  });

  it("clears an expired session and returns to login with context", async () => {
    setAuthSession(adminSession);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "token_expired",
              message: "Access token expired",
              retryable: false,
            },
          }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    render(<App />);

    expect(await screen.findByText("Your session expired. Sign in again to continue.")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/auth/login");
    expect(window.location.search).toContain("returnTo=%2Fapp%2Fsubscription");
  });
});
