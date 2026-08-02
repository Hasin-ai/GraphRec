import { useEffect, useState } from "react";
import { EntryPage } from "./pages/EntryPage";
import { AppPage } from "./pages/AppPage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RecoveryGapPage } from "./pages/RecoveryGapPage";
import { RegistrationPage } from "./pages/RegistrationPage";
import { SubscriptionPage } from "./pages/SubscriptionPage";
import { UsagePage } from "./pages/UsagePage";
import { ApiKeysPage } from "./pages/ApiKeysPage";
import { ApiKeyCreatePage } from "./pages/ApiKeyCreatePage";
import { ApiKeyRotatePage } from "./pages/ApiKeyRotatePage";
import { DatabaseUploadPage } from "./pages/DatabaseUploadPage";
import { ModelUploadPage } from "./pages/ModelUploadPage";
import { ProductsPage } from "./pages/ProductsPage";
import { EventsPage } from "./pages/EventsPage";
import { TrainingPage } from "./pages/TrainingPage";
import { DeploymentPage } from "./pages/DeploymentPage";
import { StatusPage } from "./pages/StatusPage";
import { PlatformPage } from "./pages/PlatformPage";
import {
  ForbiddenPage,
  ResetResultPage,
  ServiceUnavailablePage,
  UnauthorizedPage,
} from "./pages/StatusPages";

export function App() {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const updatePath = () => setPath(window.location.pathname);
    window.addEventListener("popstate", updatePath);
    return () => window.removeEventListener("popstate", updatePath);
  }, []);

  const rotateMatch = path.match(/^\/app\/integration\/api-keys\/([0-9a-fA-F-]{36})\/rotate$/);
  if (rotateMatch) {
    return <ApiKeyRotatePage keyId={rotateMatch[1]} />;
  }

  if (path.startsWith("/app/products")) {
    if (path === "/app/products/sync") {
      return <DatabaseUploadPage />;
    }
    return <ProductsPage />;
  }

  if (path.startsWith("/app/events")) {
    return <EventsPage />;
  }

  if (path.startsWith("/app/training")) {
    return <TrainingPage />;
  }

  if (path.startsWith("/app/deployment")) {
    return <DeploymentPage />;
  }

  if (path.startsWith("/platform")) {
    return <PlatformPage />;
  }

  switch (path) {
    case "/":
      return <EntryPage />;
    case "/auth/register":
      return <RegistrationPage />;
    case "/auth/login":
      return <LoginPage />;
    case "/auth/recover":
      return <RecoveryGapPage />;
    case "/auth/reset-result":
      return <ResetResultPage />;
    case "/unauthorized":
      return <UnauthorizedPage />;
    case "/forbidden":
      return <ForbiddenPage />;
    case "/service-unavailable":
      return <ServiceUnavailablePage />;
    case "/app":
    case "/app/integration":
      return <AppPage />;
    case "/app/data":
      return <DatabaseUploadPage />;
    case "/app/models":
      return <ModelUploadPage />;
    case "/app/subscription":
      return <SubscriptionPage />;
    case "/app/usage":
      return <UsagePage />;
    case "/app/integration/api-keys":
      return <ApiKeysPage />;
    case "/app/integration/api-keys/new":
      return <ApiKeyCreatePage />;
    case "/app/metrics":
    case "/app/status":
      return <StatusPage />;
    default:
      return <NotFoundPage />;
  }
}
