import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { AppRoutes } from "../App";
import { SessionProvider } from "../hooks/useSession";
import { ToastProvider } from "../hooks/useToast";

export function renderAt(path: string, children: ReactNode = <AppRoutes />) {
  return render(
    <SessionProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
      </ToastProvider>
    </SessionProvider>,
  );
}
