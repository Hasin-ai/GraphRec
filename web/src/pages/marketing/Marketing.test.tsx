import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearTenantSession } from "../../auth/session";
import { hasKeyLabel } from "../../lib/labels";
import { BRAND } from "../../marketing/copy";
import { LIMIT_KEYS, PLANS } from "../../marketing/plans";
import { mockFetch, signInAsAdmin, signInAsPlatform } from "../../test/helpers";
import { renderAt } from "../../test/render";

afterEach(() => vi.unstubAllGlobals());

const PLATFORM_STATUS = { items: [], status: "healthy", api_cluster: "online", database: "connected", worker_pool: "not_deployed", timestamp: "2026-09-12T00:00:00Z" };

describe("public marketing site", () => {
  it("/ signed out renders the landing page", async () => {
    mockFetch([]);
    renderAt("/");
    expect(await screen.findByRole("heading", { level: 1, name: BRAND.tagline })).toBeInTheDocument();
    const main = screen.getByRole("main");
    expect(within(main).getAllByRole("link", { name: "Create a tenant" })[0]).toHaveAttribute("href", "/register");
    expect(document.title).toBe("GraphRec: Recommendations that follow every interaction");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    for (const id of ["features", "how-it-works", "developers", "security"]) expect(document.getElementById(id)).not.toBeNull();
    const nav = screen.getByRole("navigation", { name: "Marketing" });
    expect(within(nav).getByRole("link", { name: "Features" })).toHaveAttribute("href", "/#features");
    expect(within(nav).getByRole("link", { name: "Pricing" })).toHaveAttribute("href", "/pricing");
  });

  it("/ with a tenant session redirects to /home", async () => {
    signInAsAdmin();
    mockFetch([{ path: /\/v1\/.*/, body: { items: [], total: 0 } }]);
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: BRAND.tagline })).not.toBeInTheDocument();
  });

  it("/ with a platform session still redirects to Platform Status", async () => {
    signInAsPlatform();
    mockFetch([{ path: /\/v1\/platform\/.*/, body: PLATFORM_STATUS }]);
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Platform Status" })).toBeInTheDocument();
  });

  it("the marketing header CTA follows the session", async () => {
    mockFetch([]);
    signInAsAdmin();
    renderAt("/pricing");
    const header = await screen.findByRole("banner");
    expect(within(header).getAllByRole("link", { name: "Open console" })[0]).toHaveAttribute("href", "/home");
    expect(within(header).queryByRole("link", { name: "Sign in" })).not.toBeInTheDocument();
  });

  it("the marketing header offers the platform console to an operator", async () => {
    mockFetch([]);
    signInAsPlatform();
    renderAt("/pricing");
    const header = await screen.findByRole("banner");
    expect(within(header).getAllByRole("link", { name: "Open platform console" })[0]).toHaveAttribute("href", "/admin/status");
  });

  it("the mobile menu toggles, and Escape closes it and returns focus to the toggle", async () => {
    const user = userEvent.setup();
    mockFetch([]);
    renderAt("/");
    const toggle = await screen.findByRole("button", { name: "Open menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveFocus();
  });

  it("the code sample is an ARIA tablist with arrow-key navigation", async () => {
    const user = userEvent.setup();
    mockFetch([]);
    renderAt("/");
    const tabs = await screen.findAllByRole("tab");
    // After navigation the layout moves focus to #main-content, as the console shells do.
    await waitFor(() => expect(screen.getByRole("main")).toHaveFocus());
    expect(tabs.map(t => t.textContent)).toEqual(["Python SDK", "HTTP request", "Response"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("client.storefront.recommendations.get(");
    tabs[0].focus();
    await user.keyboard("{ArrowLeft}");
    expect(tabs[2]).toHaveFocus();
    expect(tabs[2]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent('"fallback_used": false');
    expect(screen.getByText("Every result says which model and which rules produced it.")).toBeInTheDocument();
    await user.keyboard("{ArrowRight}");
    expect(tabs[0]).toHaveFocus();
  });
});

describe("/pricing", () => {
  it("renders three plans and a comparison table from PLANS", async () => {
    mockFetch([]);
    renderAt("/pricing");
    expect(await screen.findByRole("heading", { level: 1, name: "Plans and limits" })).toBeInTheDocument();
    for (const plan of PLANS) expect(screen.getByRole("heading", { level: 3, name: plan.name })).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /Seeded plan limits/ });
    expect(within(table).getAllByRole("columnheader").map(th => th.textContent)).toEqual(["Limit", "Free", "Basic", "Pro"]);
    expect(within(table).getAllByRole("rowheader")).toHaveLength(LIMIT_KEYS.length);
    expect(within(table).getAllByText("50,000").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("2,000,000").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Assigned by your platform operator")).toHaveLength(2);
    expect(screen.queryByText(/most popular/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\$\d/)).not.toBeInTheDocument();
    expect(document.title).toBe("Pricing · GraphRec");
  });

  it("signed-in tenants see View your usage instead of sign-up CTAs", async () => {
    mockFetch([]);
    signInAsAdmin();
    renderAt("/pricing");
    const links = await screen.findAllByRole("link", { name: "View your usage" });
    expect(links).toHaveLength(PLANS.length);
    expect(links[0]).toHaveAttribute("href", "/usage");
    expect(screen.queryByRole("link", { name: "Start on Free" })).not.toBeInTheDocument();
  });

  it("every plan limit key has a label in lib/labels.ts", () => {
    for (const plan of PLANS) {
      expect(Object.keys(plan.limits).sort()).toEqual([...LIMIT_KEYS].sort());
      expect(plan.price).toBeNull();
    }
    for (const key of LIMIT_KEYS) expect(hasKeyLabel(key), key).toBe(true);
  });
});

describe("brand and cross-links", () => {
  it("the auth showcase and the hero render the same BRAND.tagline", async () => {
    mockFetch([]);
    const first = renderAt("/login");
    expect(await screen.findByRole("heading", { level: 2, name: BRAND.tagline })).toBeInTheDocument();
    expect(screen.getByText(BRAND.tagline, { selector: ".auth-pitch-mobile" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to GraphRec home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Plans & limits" })).toHaveAttribute("href", "/pricing");
    first.unmount();
    renderAt("/");
    expect(await screen.findByRole("heading", { level: 1, name: BRAND.tagline })).toBeInTheDocument();
  });

  it("registration points new tenants to the plans", async () => {
    mockFetch([]);
    renderAt("/register");
    expect(await screen.findByText(/New tenants start on the Free plan/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Compare plans" })).toHaveAttribute("href", "/pricing");
  });

  it("error pages link to the right start page for each session", async () => {
    mockFetch([{ path: /\/v1\/platform\/.*/, body: PLATFORM_STATUS }, { path: /\/v1\/.*/, body: { items: [], total: 0 } }]);
    const signedOut = renderAt("/missing-page");
    expect(await screen.findByRole("link", { name: "Go to GraphRec home" })).toHaveAttribute("href", "/");
    signedOut.unmount();

    signInAsAdmin();
    const tenant = renderAt("/404");
    expect(await screen.findByRole("link", { name: "Go to Overview" })).toHaveAttribute("href", "/home");
    tenant.unmount();
    clearTenantSession();

    signInAsPlatform();
    renderAt("/error");
    expect(await screen.findByRole("link", { name: "Go to Platform Status" })).toHaveAttribute("href", "/admin/status");
  });
});
