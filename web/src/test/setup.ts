import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { clearPlatformSession, clearTenantSession } from "../auth/session";

// jsdom does not implement scrolling; the marketing layout scrolls on navigation.
window.scrollTo = (() => undefined) as typeof window.scrollTo;

afterEach(() => {
  cleanup();
  clearTenantSession();
  clearPlatformSession();
  window.sessionStorage.clear();
  window.localStorage.clear();
});
