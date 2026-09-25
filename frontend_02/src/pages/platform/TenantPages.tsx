import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { platform } from "../../api";
import { isApiError } from "../../api/client";
import type { PlatformQuotaOverride, PlatformTenant, PlatformTenantStatus } from "../../api/types";
import { useClearQuery, useQueryState } from "../../hooks/useQueryState";
import { useResource } from "../../hooks/useResource";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime, fmtNumber, shortId } from "../../lib/format";
import { Dialog } from "../../ui/Dialog";
import { Field, Select, TextInput } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { ActionsCell, Badge, Cell, DataTable, DefinitionList, ErrorBanner, FilterBar, Footnote, Panel, PanelTable, Skeleton, Tag } from "../../ui/primitives";
import { NotFoundPage } from "../errors/ErrorPages";

const STATUSES: PlatformTenantStatus[] = ["active", "suspended", "deleting", "deleted"];
const USAGE_TYPES = ["accepted_events", "recommendation_requests", "training_jobs", "training_cpu_seconds", "stored_products", "artifact_storage_bytes", "active_model_versions", "inference_replicas", "replica_runtime_minutes"];

function StatusDialog({ tenant, onClose, onDone }: { tenant: PlatformTenant; onClose: () => void; onDone: (t: PlatformTenant) => void }) {
  const [status, setStatus] = useState<string>(tenant.status === "active" ? "suspended" : "active");
  return (
    <Dialog
      title={`Change status of ${tenant.slug}`}
      width={640}
      confirmLabel="Apply status change"
      body="Review and confirm. A tenant that is not active cannot sign in and its credentials stop authenticating."
      consequence="A suspended, deleting or deleted tenant loses access to every tenant screen and its serving traffic stops. This writes an audit record."
      facts={[
        { label: "Current status", value: tenant.status },
        { label: "New status", value: status },
      ]}
      onConfirm={async () => {
        onDone(await platform.setTenantStatus(tenant.id, status as PlatformTenantStatus));
      }}
      onClose={onClose}
    >
      <Field id="d-status" label="New status">
        <Select id="d-status" value={status} onChange={setStatus} options={STATUSES} />
      </Field>

    </Dialog>
  );
}

export function PlatformTenantsPage() {
  const clearQuery = useClearQuery();
  const tenants = useResource(() => platform.listTenants(), []);
  const navigate = useNavigate();
  const { flash } = useToast();
  const [status, setStatus] = useQueryState("status", "all statuses");
  const [q, setQ] = useQueryState("q", "");
  const [changing, setChanging] = useState<PlatformTenant | null>(null);
  const items = tenants.data?.items ?? [];
  const list = items.filter((t) => (status === "all statuses" || t.status === status) && (!q.trim() || `${t.slug} ${t.name}`.toLowerCase().includes(q.trim().toLowerCase())));

  const rows = list.map((t) => (
    <tr key={t.id}>
      <td>
        <Link to={`/admin/tenants/${t.id}`} className="td-mono">
          {t.slug}
        </Link>
      </td>
      <Cell>{t.name}</Cell>
      <td>
        <Badge group="tenant" value={t.status} />
      </td>
      <Cell mono>{fmtDateTime(t.created_at)}</Cell>
      <ActionsCell actions={[{ label: "Open", onClick: () => navigate(`/admin/tenants/${t.id}`) }, { label: "Change status", onClick: () => setChanging(t) }]} />
    </tr>
  ));

  return (
    <Page crumbs={[{ label: "Platform", to: "/admin/status" }, { label: "Tenants" }]} kicker="Platform permission" title="Tenants" subtitle="Find tenants and manage their access.">
      {tenants.error ? <ErrorBanner error={tenants.error} onRetry={tenants.reload} /> : null}
      <FilterBar
        filters={[
          { id: "status", label: "Status", value: status, onChange: setStatus, options: ["all statuses", ...STATUSES] },
          { id: "q", label: "Search", value: q, onChange: setQ, placeholder: "tenant slug or name" },
        ]}
        onClear={() => clearQuery('status', 'q')}
      />
      {!tenants.data ? (tenants.loading ? <Skeleton /> : null) : (
        <DataTable minWidth={700} columns={["Tenant", "Name", "Status", "Created at", { label: "", align: "right" }]} rows={rows} count={`${list.length} of ${items.length}`} empty={{ title: items.length ? "No tenants match this filter" : "No tenants registered", body: items.length ? "Clear the filters to see all tenants." : "Registered tenant accounts appear here." }} />
      )}
      {changing ? (
        <StatusDialog
          tenant={changing}
          onClose={() => setChanging(null)}
          onDone={(t) => {
            setChanging(null);
            flash(`${t.slug} is now ${t.status}.`);
            tenants.setData((prev) => (prev ? { items: prev.items.map((x) => (x.id === t.id ? t : x)) } : prev));
          }}
        />
      ) : null}
    </Page>
  );
}

function OverrideDialog({ tenant, onClose, onDone }: { tenant: PlatformTenant; onClose: () => void; onDone: (r: PlatformQuotaOverride) => void }) {
  const [type, setType] = useState(USAGE_TYPES[0]);
  const [value, setValue] = useState("");
  return (
    <Dialog
      title={`Approve quota override for ${tenant.slug}`}
      width={640}
      confirmLabel="Approve override"
      body="An override replaces the plan limit for one usage type. Overrides already in force for other usage types are kept."
      onConfirm={async () => {
        if (value.trim() === "" || !Number.isInteger(Number(value)) || Number(value) < 0) return "The override limit must be a non-negative integer.";
        onDone(await platform.setQuotaOverrides(tenant.id, { [type]: Number(value) }));
      }}
      onClose={onClose}
    >
      <Field id="d-type" label="Usage type">
        <Select id="d-type" value={type} onChange={setType} options={USAGE_TYPES} />
      </Field>
      <Field id="d-value" label="Override limit">
        <TextInput id="d-value" value={value} onChange={setValue} mono placeholder="8000000" type="number" min={0} />
      </Field>
    </Dialog>
  );
}

export function PlatformTenantPage() {
  const { tenantId = "" } = useParams();
  return <PlatformTenantDetail key={tenantId} />;
}

function PlatformTenantDetail() {
  const { tenantId = "" } = useParams();
  const { flash } = useToast();
  const tenant = useResource(() => platform.getTenant(tenantId), [tenantId]);
  const plans = useResource(() => platform.listPlans(), []);
  const [dialog, setDialog] = useState<"status" | "override" | "plan" | null>(null);
  const quotaResource = useResource(() => platform.getTenantQuota(tenantId), [tenantId]);
  const quota = quotaResource.data;
  const [selectedPlan, setSelectedPlan] = useState('');
  const crumbs = [{ label: "Platform", to: "/admin/status" }, { label: "Tenants", to: "/admin/tenants" }, { label: shortId(tenantId), mono: true }];

  if (tenant.error && isApiError(tenant.error) && (tenant.error.status === 404 || tenant.error.status === 422)) return <NotFoundPage />;
  if (!tenant.data) {
    return (
      <Page crumbs={crumbs} kicker="Tenant" title={shortId(tenantId)}>
        {tenant.error ? <ErrorBanner error={tenant.error} onRetry={tenant.reload} /> : <Skeleton />}
      </Page>
    );
  }
  const t = tenant.data;
  return (
    <Page crumbs={[crumbs[0], crumbs[1], { label: t.slug, mono: true }]} kicker="Composed detail" title={t.name} badge={<Badge group="tenant" value={t.status} />} subtitle="Manage tenant access and approved quota overrides.">
      {tenant.error ? <ErrorBanner error={tenant.error} onRetry={tenant.reload} /> : null}
      <div className="panels">
        <Panel
          title="Status and lifecycle"
          dl={[
            { label: "Registered", value: fmtDateTime(t.created_at), mono: true },
            { label: "Tenant slug", value: t.slug, mono: true, copy: t.slug },
            { label: "Tenant identifier", value: t.id, mono: true, copy: t.id },
          ]}
          actions={[{ label: "Change status", variant: "primary", onClick: () => setDialog("status") }]}
        />
        <Panel
          title="Quota overrides"
          body="Current effective limits and approved tenant overrides."
          actions={[{ label: "Approve quota override", variant: "primary", onClick: () => setDialog("override") }]}
        >
          {quotaResource.error ? <ErrorBanner error={quotaResource.error} onRetry={quotaResource.reload} /> : null}
          {quota ? (
            <PanelTable
              columns={["Usage type", { label: "Effective limit", align: "right" }, { label: "Override", align: "right" }]}
              rows={Object.entries(quota.limits).map(([k, v]) => (
                <tr key={k}>
                  <Cell mono>{k}</Cell>
                  <Cell mono align="right">
                    {typeof v === "number" ? fmtNumber(v) : String(v)}
                  </Cell>
                  <Cell mono align="right">
                    {k in quota.overrides ? fmtNumber(quota.overrides[k] as number) : "—"}
                  </Cell>
                </tr>
              ))}
            />
          ) : null}
        </Panel>
        <Panel title="Plans" note={quota ? `Current: ${quota.plan_code}` : undefined} body="Assign an active plan. Existing usage and approved overrides are preserved." actions={[{ label: 'Assign plan', onClick: () => { setSelectedPlan(quota?.plan_id ?? ''); setDialog('plan'); }, disabled: !quota || !plans.data }]}>
          {plans.error ? <ErrorBanner error={plans.error} onRetry={plans.reload} /> : null}
          {plans.data ? (
            <PanelTable
              columns={["Plan", "Name", "Open"]}
              rows={plans.data.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link to={`/admin/plans/${p.id}`} className="td-mono">
                      {p.code}
                    </Link>
                  </td>
                  <Cell>{p.name}</Cell>
                  <td>
                    <Tag tone={p.is_active ? "ok" : "warn"}>{p.is_active ? "open" : "closed"}</Tag>
                  </td>
                </tr>
              ))}
            />
          ) : null}
        </Panel>
      </div>
      <Footnote>Every action on this page writes an audit record with the request correlation id.</Footnote>
      {dialog === "status" ? (
        <StatusDialog
          tenant={t}
          onClose={() => setDialog(null)}
          onDone={(updated) => {
            setDialog(null);
            tenant.setData(updated);
            flash(`${updated.slug} is now ${updated.status}.`);
          }}
        />
      ) : null}
      {dialog === "override" ? (
        <OverrideDialog
          tenant={t}
          onClose={() => setDialog(null)}
          onDone={() => {
            setDialog(null);
            void quotaResource.reload();
            flash(`Quota override approved for ${t.slug}.`);
          }}
        />
      ) : null}
      {dialog === 'plan' ? <Dialog title={`Assign plan for ${t.slug}`} body="The new base limits apply immediately. This does not reset usage or remove existing overrides." confirmLabel="Assign plan" onClose={() => setDialog(null)} onConfirm={async () => {
        if (!selectedPlan) return 'Select an active plan.';
        quotaResource.setData(await platform.assignTenantPlan(t.id, selectedPlan));
        setDialog(null); flash('Tenant plan updated.');
      }}><Field id="tenant-plan" label="Plan"><Select id="tenant-plan" value={selectedPlan} onChange={setSelectedPlan} options={[{ value: '', label: 'Choose a plan' }, ...(plans.data ?? []).filter(p => p.is_active).map(p => ({ value: p.id, label: p.name }))]} /></Field></Dialog> : null}
    </Page>
  );
}

export function PlatformPlansPage() {
  const plans = useResource(() => platform.listPlans(), []);
  const navigate = useNavigate();
  const rows = (plans.data ?? []).map((p) => (
    <tr key={p.id}>
      <td>
        <Link to={`/admin/plans/${p.id}`} className="td-mono">
          {p.code}
        </Link>
      </td>
      <Cell>{p.name}</Cell>
      <Cell muted>{Object.keys(p.limits).length} limits</Cell>
      <td>
        <Tag tone={p.is_active ? "ok" : "warn"}>{p.is_active ? "open" : "closed"}</Tag>
      </td>
      <ActionsCell actions={[{ label: "Open", onClick: () => navigate(`/admin/plans/${p.id}`) }]} />
    </tr>
  ));
  return (
    <Page crumbs={[{ label: "Platform", to: "/admin/status" }, { label: "Plans & Quotas" }]} kicker="Plan-management permission" title="Plans & Quotas" subtitle="Plans carry the limits that become a tenant’s effective quota. Plans are defined by migration in this release; per-tenant overrides are approved from the tenant detail.">
      {plans.error ? <ErrorBanner error={plans.error} onRetry={plans.reload} /> : null}
      {!plans.data ? (plans.loading ? <Skeleton /> : null) : <DataTable minWidth={760} columns={["Plan code", "Name", "Limits", "Active", { label: "", align: "right" }]} rows={rows} count={`${rows.length} plans`} empty={{ title: "No plans defined", body: "Plans are seeded by the database migrations." }} />}
    </Page>
  );
}

export function PlatformPlanPage() {
  const { planId = "" } = useParams();
  const plans = useResource(() => platform.listPlans(), []);
  const plan = plans.data?.find((p) => p.id === planId);
  const crumbs = [{ label: "Platform", to: "/admin/status" }, { label: "Plans & Quotas", to: "/admin/plans" }, { label: plan?.code ?? shortId(planId), mono: true }];
  if (plans.data && !plan) return <NotFoundPage />;
  if (!plan) {
    return (
      <Page crumbs={crumbs} kicker="Plan" title={shortId(planId)}>
        {plans.error ? <ErrorBanner error={plans.error} onRetry={plans.reload} /> : <Skeleton />}
      </Page>
    );
  }
  return (
    <Page crumbs={crumbs} kicker="Plan" title={plan.name} badge={<Tag tone={plan.is_active ? "ok" : "warn"}>{plan.is_active ? "open" : "closed"}</Tag>} subtitle={plan.is_active ? "Open to assignments." : "Closed: tenants already on this plan keep it."}>
      <DefinitionList items={[{ label: "Plan code", value: plan.code, mono: true, copy: plan.code }, { label: "Plan identifier", value: plan.id, mono: true, copy: plan.id }, ...Object.entries(plan.limits).map(([k, v]) => ({ label: k, value: typeof v === "number" ? fmtNumber(v) : String(v), mono: true }))]} />
      <Footnote>Limits are read-only here. Changing a plan is a migration; a tenant-specific exception is a quota override.</Footnote>
    </Page>
  );
}
