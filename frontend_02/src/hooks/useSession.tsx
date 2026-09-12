import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  SESSION_EVENT,
  clearPlatformSession,
  clearTenantSession,
  getPlatformSession,
  getTenantSession,
  hasScope,
  type PlatformSession,
  type TenantSession,
} from "../auth/session";

interface SessionContextValue {
  tenant: TenantSession | null;
  platform: PlatformSession | null;
  can: (scope: string) => boolean;
  signOutTenant: () => void;
  signOutPlatform: () => void;
  /** Bump after setTenantSession/setPlatformSession so subscribers re-read storage. */
  refresh: () => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    window.addEventListener(SESSION_EVENT, refresh);
    window.addEventListener("storage", refresh);
    // Expiry is checked lazily on read; poll so an idle tab notices its token lapsing.
    const timer = window.setInterval(refresh, 30_000);
    return () => {
      window.removeEventListener(SESSION_EVENT, refresh);
      window.removeEventListener("storage", refresh);
      window.clearInterval(timer);
    };
  }, [refresh]);

  const tenant = getTenantSession();
  const platform = getPlatformSession();
  const value = useMemo<SessionContextValue>(
    () => ({
      tenant,
      platform,
      can: (scope) => hasScope(tenant, scope),
      signOutTenant: () => clearTenantSession(),
      signOutPlatform: () => clearPlatformSession(),
      refresh,
    }),
    [tenant, platform, refresh],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}

export function useTenant(): TenantSession {
  const { tenant } = useSession();
  if (!tenant) throw new Error("useTenant requires a tenant session (route is not guarded)");
  return tenant;
}
