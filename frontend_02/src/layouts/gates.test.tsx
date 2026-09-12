import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, signInAsAdmin, signInAsDeveloper, signInAsPlatform } from "../test/helpers";
import { renderAt } from "../test/render";

afterEach(() => vi.unstubAllGlobals());

describe("authorization gates", () => {
  it("gate 1: a protected route without a session redirects to sign-in", async () => {
    mockFetch([]);
    renderAt("/credentials");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("gate 1: the platform realm has its own sign-in", async () => {
    mockFetch([]);
    renderAt("/admin/tenants");
    expect(await screen.findByRole("heading", { name: "Platform sign-in" })).toBeInTheDocument();
  });

  it("gate 3: a developer reaching an administrator route sees the terminal 403 page", async () => {
    signInAsDeveloper();
    mockFetch([{ path: /\/v1\/.*/, body: { items: [] } }]);
    renderAt("/models");
    expect(await screen.findByRole("heading", { name: "Not permitted" })).toBeInTheDocument();
  });

  it("navigation is derived from the scopes the login returned", async () => {
    signInAsDeveloper();
    mockFetch([{ path: /\/v1\/.*/, body: { items: [], total: 0 } }]);
    renderAt("/home");
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    expect(nav).toHaveTextContent("Products");
    expect(nav).toHaveTextContent("Submit Events");
    expect(nav).toHaveTextContent("Training");
    expect(nav).not.toHaveTextContent("Model Versions");
    expect(nav).not.toHaveTextContent("Usage & Quotas");
  });

  it("an administrator sees the full tenant navigation", async () => {
    signInAsAdmin();
    mockFetch([{ path: /\/v1\/.*/, body: { items: [], total: 0 } }]);
    renderAt("/home");
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    for (const label of ["API Credentials", "Products", "Training", "Model Versions", "Usage & Quotas", "Service Status"]) {
      expect(nav).toHaveTextContent(label);
    }
  });

  it("gate 4: a foreign or unknown resource is indistinguishable from a missing one", async () => {
    signInAsAdmin();
    mockFetch([
      { path: "/v1/model-versions/v-99", status: 404, body: { error: { code: "resource_not_found", message: "Model version 'v-99' not found." } } },
      { path: /\/v1\/.*/, body: { items: [] } },
    ]);
    renderAt("/models/v-99");
    expect(await screen.findByRole("heading", { name: "Not found" })).toBeInTheDocument();
    expect(screen.queryByText(/v-99/)).not.toBeInTheDocument();
  });

  it("the root resolves by identity", async () => {
    signInAsPlatform();
    mockFetch([{ path: /\/v1\/platform\/.*/, body: { items: [], status: "healthy", api_cluster: "online", database: "connected", worker_pool: "not_deployed", timestamp: "2026-09-12T00:00:00Z" } }]);
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Platform Status" })).toBeInTheDocument();
  });
});
