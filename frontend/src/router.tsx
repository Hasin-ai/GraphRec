/**
 * The route table.
 *
 * Two things about its shape are load-bearing rather than stylistic:
 *
 * **No tenant identifier appears in any tenant-realm path.** §13 forbids it and
 * the backend has no route shaped to accept one. The tenant comes from the
 * session; a path segment naming it would be attacker-controlled input that a
 * handler is tempted to trust.
 *
 * **The gates are loaders on the layouts, not checks inside components.** A
 * component that decides whether to render itself has already been rendered,
 * and its data has already been fetched. Putting gates 1–3 on the shell means
 * the refusal happens before a single tenant-scoped query is issued.
 *
 * `/403`, `/404` and `/error` are registered at the top level as standalone
 * pages, and are *also* what `RouteErrorBoundary` renders inside whichever
 * layout was active. §5 describes the second case — an error inside the tenant
 * shell keeps the shell — and the first exists because the three are
 * addressable routes that somebody will link to or type.
 */

import { createBrowserRouter } from 'react-router-dom';
import type { QueryClient } from '@tanstack/react-query';

import { PublicLayout } from './layouts/PublicLayout';
import { StateGateLayout } from './layouts/StateGateLayout';
import { TENANT_ROOT_ID, TenantLayout } from './layouts/TenantLayout';
import { PLATFORM_ROOT_ID, PlatformLayout } from './layouts/PlatformLayout';

import { RouteErrorBoundary } from './routes/errors/RouteErrorBoundary';
import { FailurePage, ForbiddenPage, NotFoundPage } from './routes/errors/pages';

import { LoginRoute } from './routes/public/Login';
import { RegisterRoute } from './routes/public/Register';
import { RecoverConfirmRoute, RecoverRoute } from './routes/public/Recover';
import { InviteAcceptRoute } from './routes/public/InviteAccept';
import { AdminLoginRoute } from './routes/public/AdminLogin';
import { TenantStatusRoute } from './routes/account/TenantStatus';
import { HomeRoute } from './routes/Home';
import { CredentialsRoute } from './routes/credentials/Credentials';
import { IntegrationRoute } from './routes/integration/Integration';
import { AccountRoute } from './routes/account/Account';
import { UsersRoute } from './routes/users/Users';
import { UserDetailRoute } from './routes/users/UserDetail';
import { AuditRoute } from './routes/audit/Audit';
import { ProductsRoute } from './routes/products/Products';
import { ProductFormRoute } from './routes/products/ProductForm';
import { ProductSyncRoute } from './routes/products/ProductSync';
import { ProductDetailRoute } from './routes/products/ProductDetail';
import { SubmitEventsRoute } from './routes/events/SubmitEvents';
import { SubmissionDetailRoute } from './routes/submissions/SubmissionDetail';
import { TrainingRoute } from './routes/training/Training';
import { TrainingDetailRoute } from './routes/training/TrainingDetail';
import { ModelsRoute } from './routes/models/Models';
import { ModelDetailRoute } from './routes/models/ModelDetail';
import { UsageRoute } from './routes/usage/Usage';
import { ServiceStatusRoute } from './routes/status/ServiceStatus';
import { adminIndexLoader } from './routes/AdminIndex';
import { rootLoader } from './routes/root';

import { platformGuard, requireRoleLoader, tenantGuard, tenantStatusGuard } from './guards';

export function createRouter(queryClient: QueryClient) {
  // The two role sets, named once. §4's table gives the Tenant Administrator
  // no catalogue access at all — that asymmetry is intentional and comes from
  // the use-case diagrams, so a developer route is not "administrator plus
  // developer" and must not be widened into one.
  const admin = requireRoleLoader(queryClient, ['tenant_administrator']);
  const developer = requireRoleLoader(queryClient, ['tenant_developer']);
  return createBrowserRouter([
    {
      path: '/',
      loader: rootLoader,
    },

    // ------------------------------------------------------------ public
    {
      element: <PublicLayout />,
      errorElement: <RouteErrorBoundary />,
      children: [
        { path: '/register', element: <RegisterRoute /> },
        { path: '/login', element: <LoginRoute /> },
        { path: '/recover', element: <RecoverRoute /> },
        { path: '/recover/confirm', element: <RecoverConfirmRoute /> },
        { path: '/invite/accept', element: <InviteAcceptRoute /> },
        { path: '/admin/login', element: <AdminLoginRoute /> },

        // Addressable error routes. Standalone, because a reader who arrives
        // at /404 by typing it may hold no session to draw a shell for.
        { path: '/403', element: <ForbiddenPage /> },
        { path: '/404', element: <NotFoundPage /> },
        { path: '/error', element: <FailurePage reference={null} /> },
      ],
    },

    // ------------------------------------------------- gate 2 landing page
    {
      element: <StateGateLayout />,
      errorElement: <RouteErrorBoundary />,
      children: [
        {
          path: '/account/tenant-status',
          loader: ({ request }) => tenantStatusGuard(queryClient, request),
          element: <TenantStatusRoute />,
        },
      ],
    },

    // ------------------------------------------------------------ tenant
    {
      id: TENANT_ROOT_ID,
      element: <TenantLayout />,
      // Gates 1 and 2 for everything below, once, before any child loader runs.
      loader: ({ request }) => tenantGuard(queryClient, request),
      errorElement: <RouteErrorBoundary />,
      children: [
        // Open to both roles.
        { path: '/home', element: <HomeRoute /> },
        { path: '/credentials', element: <CredentialsRoute /> },
        { path: '/integration', element: <IntegrationRoute /> },
        { path: '/account', element: <AccountRoute /> },

        // Tenant Administrator.
        { path: '/users', loader: admin, element: <UsersRoute /> },
        { path: '/users/:userId', loader: admin, element: <UserDetailRoute /> },
        { path: '/audit', loader: admin, element: <AuditRoute /> },
        { path: '/training', loader: admin, element: <TrainingRoute /> },
        { path: '/training/:jobId', loader: admin, element: <TrainingDetailRoute /> },
        { path: '/models', loader: admin, element: <ModelsRoute /> },
        { path: '/models/:versionId', loader: admin, element: <ModelDetailRoute /> },
        { path: '/usage', loader: admin, element: <UsageRoute /> },
        { path: '/service-status', loader: admin, element: <ServiceStatusRoute /> },

        // Tenant Developer. `/products/new` and `/products/sync` precede
        // `/products/:productId` so that neither is read as an identifier.
        { path: '/products', loader: developer, element: <ProductsRoute /> },
        { path: '/products/new', loader: developer, element: <ProductFormRoute /> },
        { path: '/products/sync', loader: developer, element: <ProductSyncRoute /> },
        { path: '/products/:productId', loader: developer, element: <ProductDetailRoute /> },
        { path: '/events/submit', loader: developer, element: <SubmitEventsRoute /> },
        {
          path: '/submissions/:submissionId',
          loader: developer,
          element: <SubmissionDetailRoute />,
        },
      ],
    },

    // ---------------------------------------------------------- platform
    {
      id: PLATFORM_ROOT_ID,
      element: <PlatformLayout />,
      // Gate 1 for the platform realm. Gate 3 is per route, because the five
      // permissions are granted independently.
      loader: ({ request }) => platformGuard(queryClient, request),
      errorElement: <RouteErrorBoundary />,
      children: [
        { path: '/admin', loader: adminIndexLoader(queryClient) },
        // Phase 15 adds the eight /admin/* routes here.
      ],
    },

    // A path that resolves to nothing is indistinguishable from one that
    // resolves to something foreign. That is the point (§13).
    { path: '*', element: <NotFoundPage /> },
  ]);
}
