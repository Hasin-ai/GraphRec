import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { DocsLayout } from "../../docs/DocsLayout";
import { DocsGettingStartedPage } from "./DocsGettingStartedPage";
import { DocsAuthPage } from "./DocsAuthPage";
import { DocsApiReferencePage } from "./DocsApiReferencePage";
import { DocsSdkPage } from "./DocsSdkPage";
import { DocsGuidesPage } from "./DocsGuidesPage";
import { DocsErrorsLimitsPage } from "./DocsErrorsLimitsPage";
import { MarketingLayout } from "../../layouts/MarketingLayout";
import { LandingPage } from "../marketing/LandingPage";
import { SessionProvider } from "../../hooks/useSession";
import { ToastProvider } from "../../hooks/useToast";

describe("Developer Documentation", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders Getting Started page with 5-minute quickstart and code blocks", async () => {
    render(
      <MemoryRouter initialEntries={["/docs"]}>
        <SessionProvider>
          <ToastProvider>
            <Routes>
              <Route element={<DocsLayout />}>
                <Route path="/docs" element={<DocsGettingStartedPage />} />
              </Route>
            </Routes>
          </ToastProvider>
        </SessionProvider>
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { level: 1, name: /Welcome to GraphRec Developer Documentation/i })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: /5-Minute Quickstart/i })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: /Core Concepts/i })).toBeDefined();
  });

  it("renders Authentication & Tenancy with header contract and scopes table", async () => {
    render(
      <MemoryRouter initialEntries={["/docs/authentication"]}>
        <SessionProvider>
          <ToastProvider>
            <Routes>
              <Route element={<DocsLayout />}>
                <Route path="/docs/authentication" element={<DocsAuthPage />} />
              </Route>
            </Routes>
          </ToastProvider>
        </SessionProvider>
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { level: 1, name: /Authentication & Multi-Tenancy/i })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: /HTTP Header Contract/i })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: /Permission Scopes Matrix/i })).toBeDefined();
    expect(screen.getByText("catalog:write")).toBeDefined();
    expect(screen.getByText("recommendations:read")).toBeDefined();
  });

  it("renders API Reference with categorized endpoints and filter search", async () => {
    render(
      <MemoryRouter initialEntries={["/docs/reference"]}>
        <SessionProvider>
          <ToastProvider>
            <Routes>
              <Route element={<DocsLayout />}>
                <Route path="/docs/reference" element={<DocsApiReferencePage />} />
              </Route>
            </Routes>
          </ToastProvider>
        </SessionProvider>
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { level: 1, name: /REST API Reference/i })).toBeDefined();
    expect(screen.getAllByText(/Recommendations & Feedback/i).length).toBeGreaterThan(0);

    // Test filter search
    const searchInput = screen.getByPlaceholderText(/Filter endpoints by path/i);
    fireEvent.change(searchInput, { target: { value: "bulk-upsert" } });
    expect(screen.getByText("/v1/products:bulk-upsert")).toBeDefined();
  });

  it("renders Python SDK Reference with methods and ecommerce helpers", async () => {
    render(
      <MemoryRouter initialEntries={["/docs/sdk"]}>
        <SessionProvider>
          <ToastProvider>
            <Routes>
              <Route element={<DocsLayout />}>
                <Route path="/docs/sdk" element={<DocsSdkPage />} />
              </Route>
            </Routes>
          </ToastProvider>
        </SessionProvider>
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { level: 1, name: /Python SDK Reference/i })).toBeDefined();
    expect(screen.getByText(/pip install graphrec-sdk/i)).toBeDefined();
    expect(screen.getAllByText(/CatalogSync/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/EventTracker/i).length).toBeGreaterThan(0);
  });

  it("renders Guides page with recommendation strategies and cold start", async () => {
    render(
      <MemoryRouter initialEntries={["/docs/guides"]}>
        <SessionProvider>
          <ToastProvider>
            <Routes>
              <Route element={<DocsLayout />}>
                <Route path="/docs/guides" element={<DocsGuidesPage />} />
              </Route>
            </Routes>
          </ToastProvider>
        </SessionProvider>
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { level: 1, name: /Integration Guides & Architecture/i })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: /1. Interaction Event Ingestion/i })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: /2. Choosing the Right Recommendation Endpoint/i })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: /3. Cold-Start Handling & Fallbacks/i })).toBeDefined();
  });

  it("renders Errors & Limits page with error dictionary and rate limits", async () => {
    render(
      <MemoryRouter initialEntries={["/docs/errors-and-limits"]}>
        <SessionProvider>
          <ToastProvider>
            <Routes>
              <Route element={<DocsLayout />}>
                <Route path="/docs/errors-and-limits" element={<DocsErrorsLimitsPage />} />
              </Route>
            </Routes>
          </ToastProvider>
        </SessionProvider>
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { level: 1, name: /Errors, Limits & Changelog/i })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: /Standard Error Envelope/i })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: /Rate Limits & Sliding Windows/i })).toBeDefined();
    expect(screen.getAllByText(/payload_too_large/i).length).toBeGreaterThan(0);
  });

  it("renders Docs links on homepage navbar, hero CTA, and footer", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <SessionProvider>
          <ToastProvider>
            <MarketingLayout>
              <LandingPage />
            </MarketingLayout>
          </ToastProvider>
        </SessionProvider>
      </MemoryRouter>
    );

    // Navbar Docs link
    const docsNavLinks = screen.getAllByRole("link", { name: "Docs" });
    expect(docsNavLinks.length).toBeGreaterThan(0);
    expect(docsNavLinks[0].getAttribute("href")).toBe("/docs");

    // Hero secondary CTA
    const heroDocsCta = screen.getByRole("link", { name: /Read API Docs/i });
    expect(heroDocsCta).toBeDefined();
    expect(heroDocsCta.getAttribute("href")).toBe("/docs");

    // Footer Developers section
    expect(screen.getByRole("navigation", { name: "Developers" })).toBeDefined();
    const apiRefFooterLink = screen.getByRole("link", { name: "API Reference" });
    expect(apiRefFooterLink.getAttribute("href")).toBe("/docs/reference");
  });
});
