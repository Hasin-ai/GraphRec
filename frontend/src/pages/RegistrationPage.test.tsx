import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RegistrationPage } from "./RegistrationPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RegistrationPage", () => {
  it("submits only the documented fields and renders the source-returned next step", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "10e9f4a0-4c8e-4cf6-bcf4-ecc8bc1d90aa",
          name: "Northwind Shop",
          status: "active",
          created_at: "2026-08-01T08:00:00Z",
          administrator_email: "admin@northwind.example",
          next_step: "Use the separately defined account-setup flow; contract TBD",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: () => "70f3e17c-29eb-4f61-9cb8-c1dc5ed80f9e" });

    render(<RegistrationPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Business name"), " Northwind   Shop ");
    await user.type(screen.getByLabelText("Administrator email"), "ADMIN@northwind.example");
    await user.click(screen.getByRole("button", { name: "Register tenant" }));

    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      name: "Northwind Shop",
      admin_email: "admin@northwind.example",
    });
    expect(init.headers).toMatchObject({
      "Idempotency-Key": "70f3e17c-29eb-4f61-9cb8-c1dc5ed80f9e",
    });
    expect(screen.getByText("Account setup is API pending")).toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  });

  it("shows a non-enumerating duplicate error and correlation reference", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "duplicate_resource",
              message: "This registration cannot be completed with the supplied information",
              correlation_id: "6f4d0a67-49a7-4757-958d-8fc9a9e61ad8",
              retryable: false,
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("crypto", { randomUUID: () => "70f3e17c-29eb-4f61-9cb8-c1dc5ed80f9e" });
    render(<RegistrationPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Business name"), "Northwind Shop");
    await user.type(screen.getByLabelText("Administrator email"), "admin@northwind.example");
    await user.click(screen.getByRole("button", { name: "Register tenant" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This registration cannot be completed with the supplied information.",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Reference: 6f4d0a67-49a7-4757-958d-8fc9a9e61ad8",
    );
  });
});
