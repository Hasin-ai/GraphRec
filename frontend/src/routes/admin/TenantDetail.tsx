/**
 * `/admin/tenants/:tenantId` — one tenant, in three separately-permitted parts.
 *
 * This is the route §8 singles out. It is gated on `platform permission`; the
 * plan and usage **sections** are gated separately, and an operator holding
 * only `platform permission` gets a `200` with those sections marked withheld
 * — explicitly **not** a whole-route `403`.
 *
 * The distinction matters because the two answers say different things. A 403
 * on the route says "you may not look at this tenant", which is false. A
 * withheld section says "you may look at this tenant, and there is a part of
 * this page that needs a permission you do not hold" — which is true, and which
 * tells the operator what to ask for. ADR 0030 records the reasoning; this page
 * is the place it is visible.
 *
 * Nothing here decides what is withheld. `sections.plan.granted` is the
 * server's, and so is `sections.plan.reason`. The console renders a heading and
 * the server's sentence, and does not compose one of its own — a client that
 * writes "you need the plan-management permission" is a client that will
 * eventually be wrong about which permission it is.
 */

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  assignPlan,
  changeTenantStatus,
  grantOverride,
  plansQuery,
  tenantDetailQuery,
  usePlatformMutation,
} from '../../api/hooks/platform';
import type { QuotaOverride, TenantDetail } from '../../api/hooks/platform';
import type { S } from '../../api/schema';
import { QueryState } from '../../components/QueryState';
import { GatedAction } from '../../components/gate5';
import {
  Badge,
  Banner,
  Breadcrumbs,
  Button,
  DefinitionList,
  Dialog,
  Input,
  Select,
  Table,
  Textarea,
} from '../../ui';
import type { Column } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';
import { formatDate, formatDateTime, formatQuantity } from '../../lib/format';
import { MEASUREMENT_STATUS_LABELS } from '../../lib/enums';

export function AdminTenantDetailRoute() {
  const { tenantId = '' } = useParams();
  const detail = useQuery(tenantDetailQuery(tenantId));

  return (
    <div className="page">
      <Breadcrumbs
        crumbs={[{ label: 'Tenants', to: '/admin/tenants' }, { label: 'Tenant' }]}
      />
      <QueryState query={detail} label="this tenant">
        {(data) => <Detail tenantId={tenantId} data={data} />}
      </QueryState>
    </div>
  );
}

function Detail({ tenantId, data }: { tenantId: string; data: TenantDetail }) {
  const [pending, setPending] = useState<'status' | 'plan' | 'override' | null>(null);
  const { tenant, sections } = data;
  const operable = sections.status.granted ? (sections.status.data?.is_operable ?? false) : false;

  return (
    <>
      <div className="page__head">
        <h1 className="page__title">{tenant.tenant_name}</h1>
        <p className="page__lede">
          <code>{tenant.tenant_code}</code> · registered {formatDate(tenant.created_at)}
        </p>
      </div>

      {/* ------------------------------------------------------- status */}
      <Section
        title="Account status"
        granted={sections.status.granted}
        reason={sections.status.reason}
      >
        {sections.status.data ? (
          <>
            <DefinitionList
              items={[
                {
                  term: 'Status',
                  value: <Badge domain="tenant" value={sections.status.data.status} />,
                },
                {
                  term: 'Changed',
                  value: formatDateTime(sections.status.data.status_changed_at),
                },
                // The reason a tenant is in the state it is in is the only part
                // of the record a person wrote. It is shown whether or not it
                // is flattering.
                { term: 'Reason', value: sections.status.data.status_reason ?? '—' },
                {
                  term: 'Operable',
                  value: sections.status.data.is_operable
                    ? 'Yes — the tenant may use the API.'
                    : 'No — every tenant-realm request is refused at gate 2.',
                },
              ]}
            />
            <div className="action-row">
              <Button onClick={() => setPending('status')}>Change status</Button>
            </div>
          </>
        ) : null}
      </Section>

      {/* --------------------------------------------------------- plan */}
      <Section title="Plan and limits" granted={sections.plan.granted} reason={sections.plan.reason}>
        {sections.plan.data ? (
          <>
            <DefinitionList
              items={[
                { term: 'Plan', value: sections.plan.data.plan_name ?? 'Not assigned' },
                { term: 'Code', value: sections.plan.data.plan_code ?? '—' },
                { term: 'Assigned', value: formatDate(sections.plan.data.assigned_at) },
              ]}
            />
            <h3 className="eyebrow">Quota exceptions</h3>
            <Overrides overrides={sections.plan.data.overrides} />
            <div className="action-row">
              <Button onClick={() => setPending('plan')}>Assign plan</Button>
              <GatedAction
                label="Grant exception"
                allowed={operable}
                reason={
                  operable
                    ? null
                    : 'This tenant is not operable, so an exception above its plan would have nothing to apply to.'
                }
                variant="secondary"
                onClick={() => setPending('override')}
              />
            </div>
          </>
        ) : null}
      </Section>

      {/* -------------------------------------------------------- usage */}
      <Section title="Usage" granted={sections.usage.granted} reason={sections.usage.reason}>
        {sections.usage.data ? (
          <>
            <p className="page__lede">Period {sections.usage.data.period}.</p>
            <Table
              caption={`Usage for ${sections.usage.data.period}`}
              columns={USAGE_COLUMNS}
              rows={sections.usage.data.rows}
              rowKey={(row) => `${row.usage_type}-${row.period}`}
            />
          </>
        ) : null}
      </Section>

      {pending === 'status' ? (
        <StatusDialog
          tenantId={tenantId}
          current={sections.status.data?.status ?? tenant.status}
          onClose={() => setPending(null)}
        />
      ) : null}
      {pending === 'plan' ? (
        <AssignPlanDialog tenantId={tenantId} onClose={() => setPending(null)} />
      ) : null}
      {pending === 'override' ? (
        <OverrideDialog tenantId={tenantId} onClose={() => setPending(null)} />
      ) : null}
    </>
  );
}

/**
 * A section, granted or withheld.
 *
 * A withheld section keeps its heading. Dropping it would leave the operator
 * with a page that looks complete and is not, and the difference between "there
 * is no plan section" and "there is one you cannot see" is the difference
 * between filing a bug and asking for a permission.
 */
function Section({
  title,
  granted,
  reason,
  children,
}: {
  title: string;
  granted: boolean;
  reason?: string | null;
  children: React.ReactNode;
}) {
  return (
    <section className="card card--wide" style={{ maxWidth: 'none' }}>
      <h2 className="card__title">{title}</h2>
      {granted ? (
        children
      ) : (
        <Banner kind="info">
          {reason ?? 'This section requires a permission this account does not hold.'}
        </Banner>
      )}
    </section>
  );
}

const USAGE_COLUMNS: readonly Column<S['PlatformUsageRowBody']>[] = [
  { key: 'type', header: 'Measure', cell: (row) => row.usage_type.replace(/_/g, ' ') },
  {
    key: 'quantity',
    header: 'Quantity',
    // Never a zero for a figure that was not measured: zero is a reading, and
    // "we did not read it" is not.
    cell: (row) =>
      row.measurement_status === 'measured' && row.quantity !== null ? (
        formatQuantity(row.quantity)
      ) : (
        <span className="muted">— {MEASUREMENT_STATUS_LABELS[row.measurement_status]}</span>
      ),
  },
];

function Overrides({ overrides }: { overrides: readonly QuotaOverride[] }) {
  if (overrides.length === 0) {
    return <p className="gated__reason">No exceptions. This tenant is on its plan's limits.</p>;
  }
  const columns: readonly Column<QuotaOverride>[] = [
    { key: 'type', header: 'Measure', cell: (row) => row.usage_type.replace(/_/g, ' ') },
    { key: 'limit', header: 'Limit', cell: (row) => row.limit_value.toLocaleString() },
    { key: 'reason', header: 'Reason', cell: (row) => row.reason },
    { key: 'granted', header: 'Granted', cell: (row) => formatDate(row.granted_at) },
    {
      key: 'expires',
      header: 'Expires',
      // Not a blank. An exception with no visible end becomes permanent by
      // nobody noticing it, so the open-ended case says so in words.
      cell: (row) => (row.expires_at ? formatDate(row.expires_at) : 'No end date'),
    },
  ];
  return (
    <Table
      caption="Quota exceptions"
      columns={columns}
      rows={[...overrides]}
      rowKey={(row) => row.override_id}
    />
  );
}

// ----------------------------------------------------------------- dialogs

const STATUS_CHOICES = [
  { value: 'active', label: 'Active — the tenant may use the API' },
  { value: 'suspended', label: 'Suspended — every request is refused at gate 2' },
  { value: 'deleting', label: 'Deleting — begins removal, and cannot be undone' },
] as const;

function StatusDialog({
  tenantId,
  current,
  onClose,
}: {
  tenantId: string;
  current: string;
  onClose: () => void;
}) {
  const [status, setStatus] = useState(current === 'active' ? 'suspended' : 'active');
  const [reason, setReason] = useState('');
  const mutation = usePlatformMutation((body: S['ChangeTenantStatusRequest']) =>
    changeTenantStatus(tenantId, body),
  );
  const form = useSubmit(mutation.mutateAsync, onClose);

  return (
    <Dialog
      title="Change tenant status"
      onClose={onClose}
      confirmLabel="Change status"
      confirmVariant={status === 'active' ? 'primary' : 'danger'}
      confirmDisabled={reason.trim().length < 4}
      busy={form.pending}
      onConfirm={() =>
        form.submit({
          status: status as S['ChangeTenantStatusRequest']['status'],
          reason: reason.trim(),
        })
      }
      wide
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <Select
        label="New status"
        value={status}
        options={STATUS_CHOICES}
        error={form.fieldErrors.status}
        onChange={(event) => setStatus(event.target.value)}
      />
      <Textarea
        label="Reason"
        required
        value={reason}
        error={form.fieldErrors.reason}
        onChange={(event) => setReason(event.target.value)}
        hint="Recorded in the audit trail. The status, the actor and the time are mechanical — this is the only part a person writes."
      />
    </Dialog>
  );
}

function AssignPlanDialog({ tenantId, onClose }: { tenantId: string; onClose: () => void }) {
  const plans = useQuery(plansQuery);
  const [planId, setPlanId] = useState('');
  const [reason, setReason] = useState('');
  const mutation = usePlatformMutation((body: S['AssignPlanRequest']) =>
    assignPlan(tenantId, body),
  );
  const form = useSubmit(mutation.mutateAsync, onClose);

  return (
    <Dialog
      title="Assign plan"
      onClose={onClose}
      confirmLabel="Assign"
      confirmDisabled={planId === ''}
      busy={form.pending}
      onConfirm={() =>
        form.submit({ plan_id: planId, reason: reason.trim() === '' ? null : reason.trim() })
      }
      wide
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <QueryState query={plans} label="the price list">
        {(data) => (
          <Select
            label="Plan"
            value={planId}
            error={form.fieldErrors.plan_id}
            // Closed plans are omitted rather than shown disabled: this list is
            // "what may be assigned", and a plan that may not be assigned is
            // not an option that needs explaining.
            options={[
              { value: '', label: 'Choose a plan' },
              ...data.plans
                .filter((plan) => plan.accepts_assignments)
                .map((plan) => ({ value: plan.plan_id, label: `${plan.plan_name}` })),
            ]}
            onChange={(event) => setPlanId(event.target.value)}
          />
        )}
      </QueryState>
      <Textarea
        label="Reason"
        value={reason}
        error={form.fieldErrors.reason}
        onChange={(event) => setReason(event.target.value)}
        hint="Optional. Assigning a plan is routine; explaining an unusual one is not."
      />
    </Dialog>
  );
}

const USAGE_TYPES = [
  { value: 'events', label: 'Events' },
  { value: 'recommendations', label: 'Recommendations' },
  { value: 'training', label: 'Training runs' },
  { value: 'products', label: 'Products' },
  { value: 'storage', label: 'Storage' },
  { value: 'service_capacity', label: 'Service capacity' },
] as const;

function OverrideDialog({ tenantId, onClose }: { tenantId: string; onClose: () => void }) {
  const [usageType, setUsageType] = useState<string>('events');
  const [limit, setLimit] = useState('0');
  const [reason, setReason] = useState('');
  const mutation = usePlatformMutation((body: S['GrantOverrideRequest']) =>
    grantOverride(tenantId, body),
  );
  const form = useSubmit(mutation.mutateAsync, onClose);

  return (
    <Dialog
      title="Grant quota exception"
      onClose={onClose}
      confirmLabel="Grant"
      confirmDisabled={reason.trim().length < 4 || limit.trim() === ''}
      busy={form.pending}
      onConfirm={() =>
        form.submit({
          usage_type: usageType as S['GrantOverrideRequest']['usage_type'],
          limit_value: Number(limit),
          reason: reason.trim(),
          expires_at: null,
        })
      }
      wide
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <Select
        label="Measure"
        value={usageType}
        options={USAGE_TYPES}
        error={form.fieldErrors.usage_type}
        onChange={(event) => setUsageType(event.target.value)}
      />
      <Input
        label="Limit"
        type="number"
        min={0}
        value={limit}
        error={form.fieldErrors.limit_value}
        onChange={(event) => setLimit(event.target.value)}
        hint="Zero is legitimate and withholds this measure entirely. It is not the same as leaving the field alone."
      />
      <Textarea
        label="Reason"
        required
        value={reason}
        error={form.fieldErrors.reason}
        onChange={(event) => setReason(event.target.value)}
        hint="Audited as a quota action. An exception nobody can explain later is an exception nobody will withdraw."
      />
    </Dialog>
  );
}
