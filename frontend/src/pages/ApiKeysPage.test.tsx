import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { ApiKeyResource, ApiKeySecretResource, AuthTokenPair } from "../api/types";
import { clearAuthSession, setAuthSession } from "../auth/session";

const adminSession: AuthTokenPair = {
  access_token: "admin-access-token",
  token_type: "Bearer",
  expires_in: 900,
  refresh_token: "admin-refresh-token",
  user_role: "tenant_administrator",
  scopes: ["keys:write", "billing:read"],
};

const key: ApiKeyResource = {
  id: "7ca0cd69-d991-4d5f-bae4-ce1ba86aa12b",
  name: "production-store",
  prefix: "gr_live_ab12CD34",
  scopes: ["catalog:read", "events:write"],
  status: "active",
  expires_at: null,
  created_at: "2026-08-01T08:00:00Z",
  last_used_at: null,
  revoked_at: null,
  grace_expires_at: null,
};

const secretKey: ApiKeySecretResource = {
  ...key,
  secret: "gr_live_abcdefghijklmnopqrstuvwxyzABCDEFGH123456789",
};

beforeEach(() => {
  clearAuthSession();
  setAuthSession(adminSession);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("API-key lifecycle pages", () => {
  it("loads the server-backed empty state without reconstructing credentials locally", async () => {
    window.history.replaceState({}, "", "/app/integration/api-keys");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    expect(await screen.findByText("No API keys yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create API key" })).toHaveAttribute("href", "/app/integration/api-keys/new");
    expect(fetchMock).toHaveBeenCalledWith("/v1/api-keys", {
      method: "GET",
      headers: { Accept: "application/json", Authorization: "Bearer admin-access-token" },
    });
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("shows only redacted rows and confirms immediate revocation", async () => {
    window.history.replaceState({}, "", "/app/integration/api-keys");
    const revoked = { ...key, status: "revoked", revoked_at: "2026-08-01T09:00:00Z" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [key] }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(revoked), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    expect(await screen.findByText("production-store")).toBeInTheDocument();
    expect(screen.getByText("gr_live_ab12CD34")).toBeInTheDocument();
    expect(screen.queryByText(/abcdefghijklmnopqrstuvwxyz/)).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Revoke" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("stop working immediately");
    await userEvent.setup().click(screen.getByRole("button", { name: "Confirm revoke" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1]).toEqual([
      `/v1/api-keys/${key.id}`,
      { method: "DELETE", headers: { Accept: "application/json", Authorization: "Bearer admin-access-token" } },
    ]);
    expect(await screen.findByText("revoked")).toBeInTheDocument();
  });

  it("creates a scoped credential and purges its one-time secret after acknowledgement", async () => {
    window.history.replaceState({}, "", "/app/integration/api-keys/new");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(secretKey), { status: 201, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Credential name"), "production-store");
    await user.click(screen.getByLabelText("catalog:read"));
    await user.click(screen.getByRole("button", { name: "Create API key" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("never be shown again");
    expect(screen.queryByText(secretKey.secret)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reveal" }));
    expect(screen.getByText(secretKey.secret)).toBeInTheDocument();
    const close = screen.getByRole("button", { name: "Close and purge secret" });
    expect(close).toBeDisabled();
    await user.click(screen.getByLabelText(/I saved this secret/));
    await user.click(close);
    expect(window.location.pathname).toBe("/app/integration/api-keys");
    expect(screen.queryByText(secretKey.secret)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/v1/api-keys", {
      method: "POST",
      body: JSON.stringify({ name: "production-store", scopes: ["catalog:read"] }),
      headers: { Accept: "application/json", Authorization: "Bearer admin-access-token", "Content-Type": "application/json" },
    });
  });

  it("limits the developer scope selector to approved catalog and event scopes", () => {
    setAuthSession({ ...adminSession, user_role: "tenant_developer", scopes: ["keys:write", "catalog:read"] });
    window.history.replaceState({}, "", "/app/integration/api-keys/new");
    vi.stubGlobal("fetch", vi.fn());
    render(<App />);

    expect(screen.getByLabelText("catalog:read")).toBeInTheDocument();
    expect(screen.getByLabelText("events:write")).toBeInTheDocument();
    expect(screen.queryByLabelText("usage:read")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("models:deploy")).not.toBeInTheDocument();
  });

  it("loads a safe rotation target and presents the replacement once", async () => {
    window.history.replaceState({}, "", `/app/integration/api-keys/${key.id}/rotate`);
    const replacement = { ...secretKey, prefix: "gr_live_ZYXW9876", grace_expires_at: "2026-08-01T09:00:00Z" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(key), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(replacement), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    const user = userEvent.setup();

    expect(await screen.findByText("production-store")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Old-secret grace period in seconds"));
    await user.type(screen.getByLabelText("Old-secret grace period in seconds"), "60");
    await user.type(screen.getByLabelText("Rotation reason"), "Scheduled rotation");
    await user.click(screen.getByLabelText(/replacement secret is shown once/));
    await user.click(screen.getByRole("button", { name: "Rotate API key" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("predecessor remains valid");
    expect(fetchMock.mock.calls[1]).toEqual([
      `/v1/api-keys/${key.id}/rotate`,
      {
        method: "POST",
        body: JSON.stringify({ grace_period_seconds: 60, reason: "Scheduled rotation" }),
        headers: { Accept: "application/json", Authorization: "Bearer admin-access-token", "Content-Type": "application/json" },
      },
    ]);
  });

  it("blocks missing keys write before any API request", () => {
    setAuthSession({ ...adminSession, scopes: ["usage:read"] });
    window.history.replaceState({}, "", "/app/integration/api-keys");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    expect(screen.getByText("API-key management is not granted.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
