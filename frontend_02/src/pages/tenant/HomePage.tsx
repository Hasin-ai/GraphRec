import { useEffect, useState } from "react";
import { apiKeys, billing, events, models, products, serving, training } from "../../api";
import { roleLabel } from "../../auth/session";
import { useResource } from "../../hooks/useResource";
import { useSession, useTenant } from "../../hooks/useSession";
import { fmtNumber } from "../../lib/format";
import { Page } from "../../ui/Page";
import { Cards, Checklist, type CardSpec, type ChecklistStep } from "../../ui/primitives";

const CARDS: (CardSpec & { scope?: string })[] = [
  { route: "/credentials", title: "API Credentials", body: "Create, rotate and revoke the credentials your integration authenticates with.", scope: "keys:write" },
  { route: "/products", title: "Products", body: "The catalog GraphRec serves from. Add, update and disable products.", scope: "catalog:read" },
  { route: "/products/sync", title: "Synchronize Catalog", body: "Bulk upsert a bounded product collection and read the result counts.", scope: "catalog:write" },
  { route: "/events/submit", title: "Submit Events", body: "Single event or bounded batch, with duplicate confirmation.", scope: "events:write" },
  { route: "/datasets", title: "Datasets", body: "Upload a JSON or CSV dataset and take the snapshots training builds from.", scope: "training:read" },
  { route: "/training", title: "Training", body: "Request a training job and follow it through the pipeline.", scope: "training:read" },
  { route: "/models", title: "Model Versions", body: "Review versions, activate, roll back and archive.", scope: "models:read" },
  { route: "/usage", title: "Usage & Quotas", body: "Measured quantities against effective limits, by period.", scope: "usage:read" },
  { route: "/service-status", title: "Service Status", body: "Availability, capacity and serving metrics.", scope: "deployments:read" },
  { route: "/integration", title: "Integration", body: "The API contract: endpoints, shapes, errors and your credential scopes." },
];

const DISMISS_KEY = "graphrec.checklist.dismissed";

function useDismissed(): [boolean, () => void] {
  const [dismissed, setDismissed] = useState(() => {
    try {
      return window.localStorage.getItem(DISMISS_KEY) === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      if (dismissed) window.localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* ignore */
    }
  }, [dismissed]);
  return [dismissed, () => setDismissed(true)];
}

/** Administrator onboarding: each step is answered by a real read, never assumed. */
function OnboardingChecklist({ onDismiss }: { onDismiss: () => void }) {
  const keys = useResource(() => apiKeys.list(), []);
  const catalog = useResource(() => products.list(), []);
  const batches = useResource(() => events.listBatches(), []);
  const jobs = useResource(() => training.list(), []);
  const versions = useResource(() => models.list(), []);
  const deployment = useResource(() => serving.deployment(), []);
  const usage = useResource(() => billing.usage(), []);

  const usableKeys = keys.data?.items?.filter((k) => k.status === "active").length ?? 0;
  const productCount = catalog.data?.total ?? 0;
  const acceptedEvents = usage.data?.dimensions?.find((d) => d.type === "accepted_events")?.used ?? 0;
  const jobCount = jobs.data?.items?.length ?? 0;
  const okJob = jobs.data?.items?.find((j) => j.status === "succeeded");
  const active = versions.data?.items?.find((v) => v.status === "active");
  const pending = (r: { loading: boolean }) => (r.loading ? "…" : null);

  const steps: ChecklistStep[] = [
    { label: "Create a credential", route: "/credentials", done: usableKeys > 0, note: pending(keys) ?? `${usableKeys} usable` },
    { label: "Synchronize the catalog", route: "/products/sync", done: productCount > 0, note: pending(catalog) ?? `${fmtNumber(productCount)} products` },
    { label: "Submit interaction events", route: "/events/submit", done: acceptedEvents > 0 || (batches.data?.length ?? 0) > 0, note: pending(usage) ?? `${fmtNumber(acceptedEvents)} this period` },
    { label: "Request training", route: "/training", done: jobCount > 0, note: pending(jobs) ?? `${jobCount} jobs` },
    { label: "Review model quality", route: "/models", done: !!okJob, note: pending(jobs) ?? (okJob ? "a job succeeded" : "no succeeded job") },
    { label: "Activate a version", route: "/models", done: !!active, note: pending(versions) ?? (active ? `${active.version_tag} active` : "none active") },
    { label: "Monitor the service", route: "/service-status", done: !!active, note: pending(deployment) ?? (deployment.data?.status ?? "unknown") },
  ];
  return <Checklist title="Getting to first recommendations" steps={steps} onDismiss={onDismiss} />;
}

export function HomePage() {
  const tenant = useTenant();
  const { can } = useSession();
  const [dismissed, dismiss] = useDismissed();
  const admin = tenant.role === "tenant_administrator";
  const cards = CARDS.filter((c) => !c.scope || can(c.scope));
  return (
    <Page kicker={roleLabel(tenant.role)} title="Home" subtitle="The services this credential may enter. Navigation is derived from the scopes granted at sign-in; anything else is refused by the API.">
      <Cards items={cards} />
      {admin && !dismissed ? <OnboardingChecklist onDismiss={dismiss} /> : null}
    </Page>
  );
}
