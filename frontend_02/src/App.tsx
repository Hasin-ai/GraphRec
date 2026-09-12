import type { ReactElement } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { SessionProvider, useSession } from "./hooks/useSession";
import { ToastProvider } from "./hooks/useToast";
import { ErrorLayout, PlatformLayout, PublicLayout, RequirePlatform, RequireScope, RequireTenant, TenantLayout } from "./layouts/Layouts";
import { FailurePage, ForbiddenPage, NotFoundPage } from "./pages/errors/ErrorPages";
import { PlatformAuditPage, PlatformStatusPage } from "./pages/platform/StatusAuditPages";
import { PlatformPlanPage, PlatformPlansPage, PlatformTenantPage, PlatformTenantsPage } from "./pages/platform/TenantPages";
import { AdminLoginPage } from "./pages/public/AdminLoginPage";
import { LoginPage } from "./pages/public/LoginPage";
import { RecoverPage } from "./pages/public/RecoverPage";
import { RegisterPage } from "./pages/public/RegisterPage";
import { SetupPage } from "./pages/public/SetupPage";
import { AccountPage } from "./pages/tenant/AccountPage";
import { CredentialsPage } from "./pages/tenant/CredentialsPage";
import { DatasetsPage } from "./pages/tenant/DatasetsPage";
import { EventsPage } from "./pages/tenant/EventsPage";
import { HomePage } from "./pages/tenant/HomePage";
import { IntegrationPage } from "./pages/tenant/IntegrationPage";
import { ModelVersionPage, ModelsPage } from "./pages/tenant/ModelsPages";
import { ProductDetailPage, ProductNewPage } from "./pages/tenant/ProductFormPages";
import { ProductSyncPage } from "./pages/tenant/ProductSyncPage";
import { ProductsPage } from "./pages/tenant/ProductsPage";
import { ServiceStatusPage } from "./pages/tenant/ServiceStatusPage";
import { SubmissionPage } from "./pages/tenant/SubmissionPage";
import { TrainingJobPage, TrainingPage } from "./pages/tenant/TrainingPages";
import { UsagePage } from "./pages/tenant/UsagePage";

/** `/` resolves by identity: tenant -> /home, platform -> /admin, otherwise sign-in. */
function Root() {
  const { tenant, platform } = useSession();
  if (tenant) return <Navigate to="/home" replace />;
  if (platform) return <Navigate to="/admin/status" replace />;
  return <Navigate to="/login" replace />;
}

const scoped = (scope: string, element: ReactElement) => <RequireScope scope={scope}>{element}</RequireScope>;

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Root />} />

      <Route element={<PublicLayout />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/setup" element={<SetupPage />} />
        <Route path="/invite/accept" element={<SetupPage />} />
        <Route path="/recover" element={<RecoverPage />} />
        <Route path="/recover/confirm" element={<Navigate to="/setup" replace />} />
        <Route path="/admin/login" element={<AdminLoginPage />} />
      </Route>

      <Route element={<RequireTenant />}>
        <Route element={<TenantLayout />}>
          <Route path="/home" element={<HomePage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/integration" element={<IntegrationPage />} />
          <Route path="/credentials" element={scoped("keys:write", <CredentialsPage />)} />
          <Route path="/products" element={scoped("catalog:read", <ProductsPage />)} />
          <Route path="/products/new" element={scoped("catalog:write", <ProductNewPage />)} />
          <Route path="/products/sync" element={scoped("catalog:write", <ProductSyncPage />)} />
          <Route path="/products/:productId" element={scoped("catalog:read", <ProductDetailPage />)} />
          <Route path="/events/submit" element={scoped("events:write", <EventsPage />)} />
          <Route path="/submissions/:submissionId" element={scoped("events:read", <SubmissionPage />)} />
          <Route path="/datasets" element={scoped("training:read", <DatasetsPage />)} />
          <Route path="/training" element={scoped("training:read", <TrainingPage />)} />
          <Route path="/training/:jobId" element={scoped("training:read", <TrainingJobPage />)} />
          <Route path="/models" element={scoped("models:read", <ModelsPage />)} />
          <Route path="/models/:versionId" element={scoped("models:read", <ModelVersionPage />)} />
          <Route path="/usage" element={scoped("usage:read", <UsagePage />)} />
          <Route path="/service-status" element={scoped("deployments:read", <ServiceStatusPage />)} />
        </Route>
      </Route>

      <Route path="/admin" element={<Navigate to="/admin/status" replace />} />
      <Route element={<RequirePlatform />}>
        <Route element={<PlatformLayout />}>
          <Route path="/admin/status" element={<PlatformStatusPage />} />
          <Route path="/admin/tenants" element={<PlatformTenantsPage />} />
          <Route path="/admin/tenants/:tenantId" element={<PlatformTenantPage />} />
          <Route path="/admin/plans" element={<PlatformPlansPage />} />
          <Route path="/admin/plans/:planId" element={<PlatformPlanPage />} />
          <Route path="/admin/audit" element={<PlatformAuditPage />} />
        </Route>
      </Route>

      <Route element={<ErrorLayout />}>
        <Route path="/403" element={<ForbiddenPage />} />
        <Route path="/404" element={<NotFoundPage />} />
        <Route path="/error" element={<FailurePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <SessionProvider>
      <ToastProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </ToastProvider>
    </SessionProvider>
  );
}
