import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, signInAsAdmin, signInAsDeveloper } from "../../test/helpers";
import { renderAt } from "../../test/render";

afterEach(() => vi.unstubAllGlobals());

const existing = {
  id: "8b0d2c6e-0000-4000-8000-000000000002",
  name: "Storefront server",
  prefix: "gr_live_7Kq4",
  scopes: ["recommendations:read"],
  status: "active",
  expires_at: null,
  created_at: "2026-09-01T00:00:00Z",
  last_used_at: null,
  revoked_at: null,
  grace_expires_at: null,
};

describe("CredentialsPage", () => {
  it("creates a credential and shows the secret exactly once", async () => {
    signInAsAdmin();
    const user = userEvent.setup();
    const { calls } = mockFetch([
      { path: "/v1/api-keys", body: { items: [existing] } },
      { method: "POST", path: "/v1/api-keys", status: 201, body: { ...existing, id: "new", name: "Event pipeline", prefix: "gr_live_2Mv8", scopes: ["catalog:read", "events:write"], secret: "gr_live_2Mv8SECRETSECRETSECRETSECRETSECRETSECRET" } },
      { path: /\/v1\/.*/, body: { items: [] } },
    ]);
    renderAt("/credentials");
    expect(await screen.findByText("Storefront server")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create credential" }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Credential name"), "Event pipeline");
    await user.click(within(dialog).getByLabelText(/Event submission/));
    await user.click(within(dialog).getByRole("button", { name: "Create credential" }));

    expect(await screen.findByTestId("secret-value")).toHaveTextContent("gr_live_2Mv8SECRET");
    const create = calls.find((c) => c.url === "/v1/api-keys" && c.init.method === "POST");
    expect(JSON.parse(create!.init.body as string)).toMatchObject({ name: "Event pipeline", scopes: ["catalog:read", "events:write"] });

    await user.click(screen.getByRole("button", { name: "I have stored it" }));
    expect(screen.queryByTestId("secret-value")).not.toBeInTheDocument();
  });

  it("keeps the dialog open with an inline error when no scope is selected", async () => {
    signInAsAdmin();
    const user = userEvent.setup();
    const { calls } = mockFetch([{ path: "/v1/api-keys", body: { items: [] } }, { path: /\/v1\/.*/, body: { items: [] } }]);
    renderAt("/credentials");
    await user.click(await screen.findByRole("button", { name: "Create credential" }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Credential name"), "x");
    await user.click(within(dialog).getByLabelText(/Catalog read/));
    await user.click(within(dialog).getByRole("button", { name: "Create credential" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/at least one/);
    expect(calls.filter((c) => c.init.method === "POST")).toHaveLength(0);
  });

  it("offers a developer only the delegatable catalog and event scopes", async () => {
    signInAsDeveloper();
    const user = userEvent.setup();
    mockFetch([{ path: "/v1/api-keys", body: { items: [] } }, { path: /\/v1\/.*/, body: { items: [] } }]);
    renderAt("/credentials");
    await user.click(await screen.findByRole("button", { name: "Create credential" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getAllByRole("checkbox")).toHaveLength(4);
    expect(within(dialog).queryByLabelText(/Model activation/)).not.toBeInTheDocument();
  });

  it("revoked credentials cannot be rotated", async () => {
    signInAsAdmin();
    mockFetch([{ path: "/v1/api-keys", body: { items: [{ ...existing, status: "revoked", revoked_at: "2026-09-02T00:00:00Z" }] } }, { path: /\/v1\/.*/, body: { items: [] } }]);
    renderAt("/credentials");
    expect(await screen.findByRole("button", { name: "Rotate" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Revoke" })).toBeDisabled();
  });
});
