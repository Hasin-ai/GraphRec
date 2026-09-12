import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { clearPlatformSession, clearTenantSession } from "../auth/session";

afterEach(() => {
  cleanup();
  clearTenantSession();
  clearPlatformSession();
  window.sessionStorage.clear();
  window.localStorage.clear();
});
