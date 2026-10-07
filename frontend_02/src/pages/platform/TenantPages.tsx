import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { platform } from "../../api";
import { isApiError } from "../../api/client";
import type { LimitConflict, PlatformPlan, PlatformQuotaOverride, PlatformTenant, PlatformTenantStatus } from "../../api/types";
import { useClearQuery, useQueryState } from "../../hooks/useQueryState";
import { useResource } from "../../hooks/useResource";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime, fmtNumber, fmtQuantity, humanize, shortId } from "../../lib/format";
import { Dialog } from "../../ui/Dialog";
import { Field, Select, TextInput } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { ActionsCell, Badge, Cell, DataTable, DefinitionList, ErrorBanner, FilterBar, Footnote, Panel, PanelTable, Skeleton, Tag } from "../../ui/primitives";
import { NotFoundPage } from "../errors/ErrorPages";
import { humanizeKey } from "../../lib/labels";
import { ReasonField } from "../../ui/ReasonField";

const STATUSES: PlatformTenantStatus[] = ["active", "suspended", "deleting", "deleted"];
const USAGE_TYPES = ["accepted_events", "recommendation_requests", "training_jobs", "training_cpu_seconds", "stored_products", "artifact_storage_bytes", "active_model_versions", "inference_replicas", "replica_runtime_minutes"];

function StatusDialog({ tenant, onClose, onDone }: { tenant: PlatformTenant; onClose: () => void; onDone: (t: PlatformTenant) => void }) {
  const [status, setStatus] = useState<string>(tenant.status === "active" ? "suspended" : "active");
  const [reason, setReason] = useState("");
  return (
    <Dialog
      confirmDisabled={reason.trim().length < 3}
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
        onDone(await platform.setTenantStatus(tenant.id, status as PlatformTenantStatus, reason));
      }}
      onClose={onClose}
    >
      <Field id="d-status" label="New status">
        <Select id="d-status" value={status} onChange={setStatus} options={STATUSES} />
      </Field>
      <ReasonField id="d-status-reason" value={reason} onChange={setReason} required />

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

/**
 * Two-step confirmation for limit changes. The first attempt is sent without
 * acknowledgement; if the API answers 409 limit_below_usage, the conflicts are
 * shown and the operator must tick the box before the change is resent.
 */
function useBelowUsageGuard() {
  const [conflicts, setConflicts] = useState<LimitConflict[] | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  async function attempt<T>(send: (acknowledge: boolean) => Promise<T>): Promise<T | string> {
    if (conflicts && !acknowledged) return "Confirm that you want to apply limits below current usage, or change the values.";
    try {
      return await send(!!conflicts && acknowledged);
    } catch (caught) {
      if (isApiError(caught) && caught.code === "limit_below_usage") {
        setConflicts((caught.details.conflicts as LimitConflict[] | undefined) ?? []);
        setAcknowledged(false);
        return "These limits are below what is already stored. Review the impact below.";
      }
      throw caught;
    }
  }
  const reset = () => { setConflicts(null); setAcknowledged(false); };
  const notice = conflicts ? <div className="limit-conflicts" role="alert">
    <strong>Below current usage</strong>
    <p>Nothing is deleted, but each tenant below cannot add more until its usage drops under the new limit. Edits to existing data keep working.</p>
    <ul>{conflicts.map((c, i) => <li key={i}>{c.tenant_name ? <b>{c.tenant_name}: </b> : null}{humanize(c.limit_name)} — {fmtNumber(c.used)} stored, new limit {fmtNumber(c.limit)} ({fmtNumber(c.over_by)} over)</li>)}</ul>
    <label className="check"><input type="checkbox" checked={acknowledged} onChange={e => setAcknowledged(e.target.checked)} /> Apply anyway and block further growth</label>
  </div> : null;
  return { attempt, notice, reset, isResult: <T,>(value: T | string): value is T => typeof value !== "string" };
}

function OverrideDialog({ tenant, onClose, onDone }: { tenant: PlatformTenant; onClose: () => void; onDone: (r: PlatformQuotaOverride) => void }) {
  const [type, setType] = useState(USAGE_TYPES[0]);
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const guard = useBelowUsageGuard();
  return (
    <Dialog
      title={`Approve quota override for ${tenant.slug}`}
      width={640}
      confirmLabel="Approve override"
      body="An override replaces the plan limit for one usage type. Overrides already in force for other usage types are kept."
      onConfirm={async () => {
        if (value.trim() === "" || !Number.isInteger(Number(value)) || Number(value) < 0) return "The override limit must be a non-negative integer.";
        const result = await guard.attempt(ack => platform.setQuotaOverrides(tenant.id, { [type]: Number(value) }, ack, reason));
        if (!guard.isResult(result)) return result;
        onDone(result);
      }}
      onClose={onClose}
    >
      <Field id="d-type" label="Usage type">
        <Select id="d-type" value={type} onChange={v => { setType(v); guard.reset(); }} options={USAGE_TYPES} />
      </Field>
      <Field id="d-value" label="Override limit">
        <TextInput id="d-value" value={value} onChange={v => { setValue(v); guard.reset(); }} mono placeholder="8000000" type="number" min={0} />
      </Field>
      <ReasonField id="d-override-reason" value={reason} onChange={setReason} />
      {guard.notice}
    </Dialog>
  );
}

function RecoveryDialog({ tenant, onClose, onDone }: { tenant: PlatformTenant; onClose: () => void; onDone: (token: string, expires: string) => void }) {
  const [email, setEmail] = useState("");
  const [reason, setReason] = useState("");
  return <Dialog title={`Issue recovery token for ${tenant.slug}`} width={640}
    body="Issue a one-time token for an active account. Deliver it to the account owner through a trusted channel. A new token revokes earlier unused tokens."
    confirmLabel="Issue token" onClose={onClose} onConfirm={async () => {
      if (!email.trim()) return "Enter the account email.";
      const issued = await platform.issueRecovery(tenant.id, email.trim(), reason);
      onDone(issued.recovery_token, issued.expires_at);
    }}>
    <Field id="recovery-account" label="Account email">
      <TextInput id="recovery-account" type="email" value={email} onChange={setEmail} autoComplete="off" required />
    </Field>
    <ReasonField id="recovery-reason" value={reason} onChange={setReason} />
  </Dialog>;
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
  const [dialog, setDialog] = useState<"status" | "override" | "plan" | "recovery" | null>(null);
  const [recovery, setRecovery] = useState<{ token: string; expires: string } | null>(null);
  const quotaResource = useResource(() => platform.getTenantQuota(tenantId), [tenantId]);
  const tenantUsage = useResource(() => platform.getTenantUsage(tenantId), [tenantId]);
  const quota = quotaResource.data;
  const [selectedPlan, setSelectedPlan] = useState('');
  const [planReason, setPlanReason] = useState("");
  const planGuard = useBelowUsageGuard();
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
        <Panel title="Account recovery" body="Issue a one-time reset token for an active tenant account. The secret appears only here after issue."
          actions={[{ label: "Issue recovery token", onClick: () => { setRecovery(null); setDialog("recovery"); }, disabled: t.status !== "active" }]}>
          {recovery ? <div>
            <p className="footnote">Copy this token now and deliver it securely. Expires {fmtDateTime(recovery.expires)}.</p>
            <code style={{ overflowWrap: "anywhere" }}>{recovery.token}</code>
            <p className="footnote">Recovery page: /recover</p>
            <button type="button" className="btn btn-secondary" onClick={() => setRecovery(null)}>Hide token</button>
          </div> : null}
        </Panel>
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
                  <td title={k}>{humanizeKey(k)}</td>
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
        <Panel title="Current usage" body="Measured tenant totals and effective limits for the current period; no customer event payloads are shown." actions={[{ label: 'Refresh usage', onClick: () => void tenantUsage.reload(), disabled: tenantUsage.loading }]}>
          {tenantUsage.error ? <ErrorBanner error={tenantUsage.error} onRetry={tenantUsage.reload} /> : null}
          {!tenantUsage.data && tenantUsage.loading ? <Skeleton rows={3} /> : null}
          {tenantUsage.data ? <>
            <PanelTable columns={['Usage type', { label: 'Used', align: 'right' }, { label: 'Limit', align: 'right' }, { label: 'Remaining', align: 'right' }]}
              rows={tenantUsage.data.dimensions.map(d => <tr key={d.type}>
                <Cell>{humanize(d.type)}</Cell>
                <Cell mono align="right">{d.measured === false ? 'Not measured' : fmtQuantity(d.used, d.unit)}</Cell>
                <Cell mono align="right">{d.limit === null ? 'No limit' : fmtQuantity(d.limit, d.unit)}</Cell>
                <Cell align="right">{d.remaining === null ? '—' : d.limit !== null && d.used > d.limit ? <span className="over-by">{fmtQuantity(d.used - d.limit, d.unit)} over</span> : fmtQuantity(d.remaining, d.unit)}</Cell>
              </tr>)} />
            <p className="footnote">Period {fmtDateTime(tenantUsage.data.period_start)} – {fmtDateTime(tenantUsage.data.period_end)}. Reconciled {fmtDateTime(tenantUsage.data.last_reconciled_at)}.</p>
          </> : null}
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
            void tenantUsage.reload();
            flash(`Quota override approved for ${t.slug}.`);
          }}
        />
      ) : null}
      {dialog === 'plan' ? <Dialog title={`Assign plan for ${t.slug}`} body="The new base limits apply immediately. This does not reset usage or remove existing overrides." confirmLabel="Assign plan" onClose={() => { setDialog(null); planGuard.reset(); }} onConfirm={async () => {
        if (!selectedPlan) return 'Select an active plan.';
        const result = await planGuard.attempt(ack => platform.assignTenantPlan(t.id, selectedPlan, ack, planReason));
        if (!planGuard.isResult(result)) return result;
        quotaResource.setData(result);
        void tenantUsage.reload();
        setDialog(null); planGuard.reset(); flash(result.warnings?.length ? 'Tenant plan updated. The tenant is now over a storage limit.' : 'Tenant plan updated.');
      }}><Field id="tenant-plan" label="Plan"><Select id="tenant-plan" value={selectedPlan} onChange={v => { setSelectedPlan(v); planGuard.reset(); }} options={[{ value: '', label: 'Choose a plan' }, ...(plans.data ?? []).filter(p => p.is_active).map(p => ({ value: p.id, label: p.name }))]} /></Field><ReasonField id="tenant-plan-reason" value={planReason} onChange={setPlanReason} />{planGuard.notice}</Dialog> : null}
      {dialog === "recovery" ? <RecoveryDialog tenant={t} onClose={() => setDialog(null)} onDone={(token, expires) => {
        setDialog(null); setRecovery({ token, expires }); flash("One-time recovery token issued.");
      }} /> : null}
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
      <Cell muted>{typeof p.limits.stored_products === "number" ? `${fmtNumber(p.limits.stored_products)} products` : ""}{typeof p.limits.accepted_events === "number" ? ` · ${fmtNumber(p.limits.accepted_events)} events/period` : ""}{typeof p.limits.stored_products !== "number" && typeof p.limits.accepted_events !== "number" ? `${Object.keys(p.limits).length} limits` : ""}</Cell>
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
  const { flash } = useToast();
  const [editing, setEditing] = useState(false);
  const [editReason, setEditReason] = useState("");
  const editGuard = useBelowUsageGuard();
  const [name, setName] = useState("");
  const [active, setActive] = useState("true");
  const [limits, setLimits] = useState<Record<string, string>>({});
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
    <Page crumbs={crumbs} kicker="Plan" title={plan.name} badge={<Tag tone={plan.is_active ? "ok" : "warn"}>{plan.is_active ? "open" : "closed"}</Tag>} subtitle={plan.is_active ? "Open to assignments." : "Closed: tenants already on this plan keep it."} actions={[{ label: "Edit plan", variant: "primary", onClick: () => {
      setName(plan.name);
      setActive(String(plan.is_active));
      setLimits(Object.fromEntries(Object.entries(plan.limits).map(([key, value]) => [key, String(value)])));
      setEditing(true);
    } }]}>
      <DefinitionList items={[{ label: "Plan code", value: plan.code, mono: true, copy: plan.code }, { label: "Plan identifier", value: plan.id, mono: true, copy: plan.id }, ...Object.entries(plan.limits).map(([k, v]) => ({ label: humanizeKey(k), value: typeof v === "number" ? fmtNumber(v) : String(v) }))]} />
      <Footnote>Editing a plan updates base limits for every assigned tenant without resetting usage or removing approved overrides. Changes are audited.</Footnote>
      {editing ? <Dialog title={`Edit ${plan.code} plan`} width={680} body="Review base limits carefully; changes apply to all tenants assigned to this plan." confirmLabel="Apply plan changes" onClose={() => { setEditing(false); editGuard.reset(); }} onConfirm={async () => {
        const parsed: Record<string, number> = {};
        for (const [key, value] of Object.entries(limits)) {
          const number = Number(value);
          if (value.trim() === "" || !Number.isSafeInteger(number) || number < 0 || number > 9_000_000_000_000_000) return `${key} must be an integer from 0 to 9,000,000,000,000,000.`;
          parsed[key] = number;
        }
        if (!name.trim()) return "Enter a plan name.";
        const result = await editGuard.attempt(ack => platform.updatePlan(plan.id, { name: name.trim(), is_active: active === "true", limits: parsed }, ack, editReason));
        if (!editGuard.isResult(result)) return result;
        const updated: PlatformPlan = result;
        plans.setData(previous => previous ? previous.map(item => item.id === updated.id ? updated : item) : null);
        setEditing(false); editGuard.reset();
        flash(updated.warnings?.length ? `${updated.code} plan updated. ${updated.warnings.length} tenant limit(s) are now below usage.` : `${updated.code} plan updated.`);
      }}>
        <Field id="plan-name" label="Plan name"><TextInput id="plan-name" value={name} onChange={setName} /></Field>
        <Field id="plan-active" label="Open to new assignments"><Select id="plan-active" value={active} onChange={setActive} options={[{ value: "true", label: "Open" }, { value: "false", label: "Closed" }]} /></Field>
        {Object.keys(plan.limits).map(key => <Field key={key} id={`limit-${key}`} label={humanizeKey(key)}><TextInput id={`limit-${key}`} value={limits[key] ?? ""} onChange={value => { setLimits(current => ({ ...current, [key]: value })); editGuard.reset(); }} type="number" min={0} max={9_000_000_000_000_000} /></Field>)}
        <ReasonField id="plan-edit-reason" value={editReason} onChange={setEditReason} />
        {editGuard.notice}
      </Dialog> : null}
    </Page>
  );
}
