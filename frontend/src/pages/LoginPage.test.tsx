import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { clearAuthSession } from "../auth/session";

const tokenPair = {
  access_token: "access-token",
  token_type: "Bearer",
  expires_in: 900,
  refresh_token: "refresh-token",
  user_role: "tenant_administrator",
  scopes: ["keys:write", "usage:read"],
};

beforeEach(() => {
  clearAuthSession();
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/auth/login");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LoginPage", () => {
  it("submits the documented fields, keeps tokens in memory, and opens the protected app", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(tokenPair), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Email"), " ADMIN@EXAMPLE.ORG ");
    await user.type(screen.getByLabelText("Password"), "secret-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      email: "admin@example.org",
      password: "secret-password",
    });
    expect(await screen.findByText("Welcome to GraphRec.")).toBeInTheDocument();
    expect(screen.getByText("tenant administrator", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("keys:write")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/app");
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("shows the generic authentication error and correlation reference", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "authentication_failed",
              message: "Authentication failed",
              correlation_id: "26bb70c4-11e1-4679-bc9d-4cd88d19492c",
              retryable: false,
            },
          }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    render(<App />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "admin@example.org");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The supplied credentials could not be authenticated.",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Reference: 26bb70c4-11e1-4679-bc9d-4cd88d19492c",
    );
  });

  it("rejects an external return target", async () => {
    window.history.replaceState({}, "", "/auth/login?returnTo=//evil.example/phish");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(tokenPair), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(<App />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "admin@example.org");
    await user.type(screen.getByLabelText("Password"), "secret-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Welcome to GraphRec.")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/app");
    expect(window.location.host).not.toBe("evil.example");
  });

  it("shows an honest recovery gap without collecting recovery data", () => {
    window.history.replaceState({}, "", "/auth/recover");
    render(<App />);

    expect(screen.getByText("Password recovery is not enabled.")).toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("guards a direct app route when no in-memory session exists", () => {
    window.history.replaceState({}, "", "/app");
    render(<App />);

    expect(screen.getByText("Sign in to open this workspace.")).toBeInTheDocument();
    expect(screen.queryByText("Granted scopes")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/auth/login?returnTo=%2Fapp",
    );
  });
});
