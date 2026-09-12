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
  it("sends name and email with an Idempotency-Key and shows the one-time setup link", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch([{ method: "POST", path: "/v1/tenants", status: 201, body: created }]);
    renderAt("/register");

    await user.type(screen.getByLabelText("Business name"), "  Northgate   Supply ");
    await user.type(screen.getByLabelText("Administrator email"), "Dana@Northgate.example");
    await user.click(screen.getByRole("button", { name: "Create tenant" }));

    expect(await screen.findByRole("heading", { name: "Tenant created" })).toBeInTheDocument();
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
    await user.type(screen.getByLabelText("Administrator email"), "dana@northgate.example");
    await user.click(screen.getByRole("button", { name: "Create tenant" }));
    expect(await screen.findByText("This registration was replayed")).toBeInTheDocument();
    expect(screen.queryByTestId("setup-link")).not.toBeInTheDocument();
  });

  it("reports a repeated registration inline and keeps the form filled", async () => {
    const user = userEvent.setup();
    mockFetch([{ method: "POST", path: "/v1/tenants", status: 409, body: { error: { code: "duplicate_resource", message: "A tenant with this name already exists" } } }]);
    renderAt("/register");
    await user.type(screen.getByLabelText("Business name"), "Kelder Tools");
    await user.type(screen.getByLabelText("Administrator email"), "ops@kelder.example");
    await user.click(screen.getByRole("button", { name: "Create tenant" }));
    expect(await screen.findByText("This registration already exists")).toBeInTheDocument();
    expect(screen.getByLabelText("Business name")).toHaveValue("Kelder Tools");
    expect(screen.getByLabelText("Administrator email")).toHaveValue("ops@kelder.example");
  });
});
