import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getTenantSession } from "../../auth/session";
import { mockFetch, tokenPair } from "../../test/helpers";
import { renderAt } from "../../test/render";

afterEach(() => vi.unstubAllGlobals());

describe("LoginPage", () => {
  it("signs in, stores the session and lands on Home", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch([
      { method: "POST", path: "/v1/auth/login", body: tokenPair() },
      { path: /\/v1\/.*/, body: { items: [], total: 0 } },
    ]);
    renderAt("/login");

    await user.type(screen.getByLabelText("Email"), "Dana@Northgate.example");
    await user.type(screen.getByLabelText("Password"), "correct horse");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Home" })).toBeInTheDocument());
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ email: "dana@northgate.example", password: "correct horse" });
    expect(getTenantSession()?.role).toBe("tenant_administrator");
    expect(getTenantSession()?.scopes).toContain("models:deploy");
  });

  it("shows one non-disclosing message for a failed attempt", async () => {
    const user = userEvent.setup();
    mockFetch([{ method: "POST", path: "/v1/auth/login", status: 401, body: { error: { code: "authentication_failed", message: "Authentication failed" } } }]);
    renderAt("/login");

    await user.type(screen.getByLabelText("Email"), "nobody@example.org");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Sign-in failed")).toBeInTheDocument();
    expect(screen.getByText(/credentials supplied are not valid/)).toBeInTheDocument();
    expect(getTenantSession()).toBeNull();
  });

  it("reports a rate limit with the retry window", async () => {
    const user = userEvent.setup();
    mockFetch([{ method: "POST", path: "/v1/auth/login", status: 429, body: { error: { code: "rate_limit_exceeded", message: "limit", retry_after_seconds: 42 } } }]);
    renderAt("/login");
    await user.type(screen.getByLabelText("Email"), "a@b.c");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(/42 seconds/)).toBeInTheDocument();
  });
});
