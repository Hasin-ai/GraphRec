import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch } from "../../test/helpers";
import { renderAt } from "../../test/render";

afterEach(() => vi.unstubAllGlobals());

const created = {
  id: "5c1b1d7e-0000-4000-8000-000000000001",
  name: "Northgate Supply",
  status: "active",
  created_at: "2026-09-12T08:00:00Z",
  administrator_email: "dana@northgate.example",
  next_step: "Open the setup link to choose a password.",
  setup_token: "tok_abc123",
  setup_token_expires_at: "2026-09-13T08:00:00Z",
};

describe("RegisterPage", () => {
  it("creates the account and signs the administrator in with the chosen password", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch([
      { method: "POST", path: "/v1/tenants", status: 201, body: created },
      { method: "POST", path: "/v1/auth/setup-password", status: 200, body: { access_token: "a", refresh_token: "r", token_type: "Bearer", expires_in: 900, email: "dana@northgate.example", scopes: ["users:write"], role: "tenant_administrator" } },
    ]);
    renderAt("/register");
    await user.type(screen.getByLabelText("Business name"), "Northgate Supply");
    await user.type(screen.getByLabelText("Work email"), "Dana@Northgate.example");
    await user.type(screen.getByLabelText("Password"), "a-good-password");
    await user.type(screen.getByLabelText("Confirm password"), "a-good-password");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await vi.waitFor(() => expect(calls).toHaveLength(2));
    expect(JSON.parse(calls[1].init.body as string)).toEqual({ setup_token: "tok_abc123", password: "a-good-password", email: "dana@northgate.example" });
    expect(screen.queryByTestId("setup-link")).not.toBeInTheDocument();
  });

  it("refuses mismatched passwords before calling the API", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch([]);
    renderAt("/register");
    await user.type(screen.getByLabelText("Business name"), "Northgate Supply");
    await user.type(screen.getByLabelText("Work email"), "dana@northgate.example");
    await user.type(screen.getByLabelText("Password"), "a-good-password");
    await user.type(screen.getByLabelText("Confirm password"), "another-password");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("The passwords do not match.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("sends name and email with an Idempotency-Key and falls back to the one-time setup link if activation fails", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch([
      { method: "POST", path: "/v1/tenants", status: 201, body: created },
      { method: "POST", path: "/v1/auth/setup-password", status: 503, body: { error: { code: "service_unavailable", message: "x" } } },
    ]);
    renderAt("/register");

    await user.type(screen.getByLabelText("Business name"), "  Northgate   Supply ");
    await user.type(screen.getByLabelText("Work email"), "Dana@Northgate.example");
    await user.type(screen.getByLabelText("Password"), "a-good-password");
    await user.type(screen.getByLabelText("Confirm password"), "a-good-password");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("heading", { name: "Account created" })).toBeInTheDocument();
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toMatch(/.+/);
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ name: "Northgate   Supply", admin_email: "dana@northgate.example" });
    expect(screen.getByTestId("setup-link").textContent).toBe("http://localhost/setup#token=tok_abc123");
  });

  it("explains a replayed registration without a token", async () => {
    const user = userEvent.setup();
    mockFetch([{ method: "POST", path: "/v1/tenants", status: 200, body: { ...created, setup_token: null, setup_token_expires_at: null } }]);
    renderAt("/register");
    await user.type(screen.getByLabelText("Business name"), "Northgate Supply");
    await user.type(screen.getByLabelText("Work email"), "dana@northgate.example");
    await user.type(screen.getByLabelText("Password"), "a-good-password");
    await user.type(screen.getByLabelText("Confirm password"), "a-good-password");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("This registration was replayed")).toBeInTheDocument();
    expect(screen.queryByTestId("setup-link")).not.toBeInTheDocument();
  });

  it("reports a repeated registration inline and keeps the form filled", async () => {
    const user = userEvent.setup();
    mockFetch([{ method: "POST", path: "/v1/tenants", status: 409, body: { error: { code: "duplicate_resource", message: "A tenant with this name already exists" } } }]);
    renderAt("/register");
    await user.type(screen.getByLabelText("Business name"), "Kelder Tools");
    await user.type(screen.getByLabelText("Work email"), "ops@kelder.example");
    await user.type(screen.getByLabelText("Password"), "a-good-password");
    await user.type(screen.getByLabelText("Confirm password"), "a-good-password");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("This registration already exists")).toBeInTheDocument();
    expect(screen.getByLabelText("Business name")).toHaveValue("Kelder Tools");
    expect(screen.getByLabelText("Work email")).toHaveValue("ops@kelder.example");
  });

  it("reports only the field the API says is duplicated (D15)", async () => {
    const user = userEvent.setup();
    mockFetch([{ method: "POST", path: "/v1/tenants", status: 409, body: { error: { code: "duplicate_resource", message: "x", details: { fields: [{ field: "name", message: "This business name is already registered. Choose a different name." }] } } } }]);
    renderAt("/register");
    await user.type(screen.getByLabelText("Business name"), "Kelder Tools");
    await user.type(screen.getByLabelText("Work email"), "new@kelder.example");
    await user.type(screen.getByLabelText("Password"), "a-good-password");
    await user.type(screen.getByLabelText("Confirm password"), "a-good-password");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Choose a different business name and submit again.")).toBeInTheDocument();
    expect(screen.getByText("This business name is already registered. Choose a different name.")).toBeInTheDocument();
    expect(screen.queryByText(/with this administrator email was already registered/)).not.toBeInTheDocument();
  });
});
