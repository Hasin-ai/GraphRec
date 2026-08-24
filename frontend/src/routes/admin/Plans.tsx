/**
 * `/admin/plans` — the price list, and `/admin/plans/:planId` — one plan.
 *
 * Two components in one file because the second is mostly the first's row
 * expanded, and splitting them would put the limit vocabulary in two places.
 *
 * `accepts_assignments` is rendered as "open to new tenants" rather than as
 * "active", because the column is a fact about what may be *assigned* and
 * "active" reads as a statement about the plan's existing tenants — which keep
 * their plan when it closes. That is the whole point of closing one.
 */

import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  closePlan,
  createPlan,
  planDetailQuery,
  plansQuery,
  updatePlan,
  usePlatformMutation,
} from '../../api/hooks/platform';
import type { PlanBody } from '../../api/hooks/platform';
import type { S } from '../../api/schema';
import { QueryState } from '../../components/QueryState';
import { GatedAction } from '../../components/gate5';
import {
  Banner,
  Breadcrumbs,
  Button,
  DefinitionList,
  Dialog,
  Input,
  Table,
  Textarea,
  ToneBadge,
} from '../../ui';
import type { Column } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';
import { formatBytes, formatNumber } from '../../lib/format';

const LIMIT_FIELDS = [
  { key: 'event_limit', label: 'Events', hint: 'Per billing period.' },
  { key: 'recommendation_limit', label: 'Recommendations', hint: 'Per billing period.' },
  { key: 'training_limit', label: 'Training runs', hint: 'Per billing period.' },
  { key: 'product_limit', label: 'Products', hint: 'A ceiling on the catalogue, not a rate.' },
  { key: 'storage_limit_bytes', label: 'Storage (bytes)', hint: 'Artifacts and embeddings.' },
] as const;

type LimitKey = (typeof LIMIT_FIELDS)[number]['key'];

export function AdminPlansRoute() {
  const plans = useQuery(plansQuery);
  const [creating, setCreating] = useState(false);

  const columns: readonly Column<PlanBody>[] = [
    {
      key: 'name',
      header: 'Plan',
      cell: (row) => <Link to={`/admin/plans/${row.plan_id}`}>{row.plan_name}</Link>,
    },
    { key: 'code', header: 'Code', cell: (row) => <code>{row.plan_code}</code> },
    { key: 'events', header: 'Events', cell: (row) => formatNumber(row.event_limit) },
    {
      key: 'recs',
      header: 'Recommendations',
      cell: (row) => formatNumber(row.recommendation_limit),
    },
    { key: 'training', header: 'Training', cell: (row) => formatNumber(row.training_limit) },
    { key: 'products', header: 'Products', cell: (row) => formatNumber(row.product_limit) },
    { key: 'storage', header: 'Storage', cell: (row) => formatBytes(row.storage_limit_bytes) },
    {
      key: 'open',
      header: 'Open to new tenants',
      cell: (row) => (
        <ToneBadge tone={row.accepts_assignments ? 'ok' : 'neu'}>
          {row.accepts_assignments ? 'Open' : 'Closed'}
        </ToneBadge>
      ),
    },
    { key: 'tenants', header: 'Assigned', cell: (row) => formatNumber(row.assigned_tenants) },
  ];

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Plans</h1>
        <p className="page__lede">
          What a tenant is entitled to. Editing a limit changes it for every tenant on the plan;
          a single tenant's exception is granted on that tenant, not here.
        </p>
      </div>

      <p className="action-row">
        <Button onClick={() => setCreating(true)}>Create plan</Button>
      </p>

      <QueryState
        query={plans}
        shape="table"
        columns={columns.length}
        label="the price list"
        isEmpty={(data) => data.plans.length === 0}
        empty={{
          headline: 'No plans',
          body: 'A tenant registered without a plan has no limits to enforce. Create one.',
        }}
      >
        {(data) => (
          <Table
            caption="Pricing plans"
            columns={columns}
            rows={data.plans}
            rowKey={(row) => row.plan_id}
          />
        )}
      </QueryState>

      {creating ? <CreateDialog onClose={() => setCreating(false)} /> : null}
    </div>
  );
}

export function AdminPlanDetailRoute() {
  const { planId = '' } = useParams();
  const detail = useQuery(planDetailQuery(planId));
  const [editing, setEditing] = useState(false);
  const [closing, setClosing] = useState(false);

  return (
    <div className="page">
      <Breadcrumbs crumbs={[{ label: 'Plans', to: '/admin/plans' }, { label: 'Plan' }]} />
      <QueryState query={detail} label="this plan">
        {(data) => (
          <>
            <div className="page__head">
              <h1 className="page__title">{data.plan.plan_name}</h1>
              <p className="page__lede">
                <code>{data.plan.plan_code}</code>
                {data.plan.description ? ` · ${data.plan.description}` : ''}
              </p>
            </div>

            <DefinitionList
              items={[
                ...LIMIT_FIELDS.map((field) => ({
                  term: field.label,
                  value:
                    field.key === 'storage_limit_bytes'
                      ? formatBytes(data.plan[field.key])
                      : formatNumber(data.plan[field.key]),
                })),
                {
                  term: 'Open to new tenants',
                  value: data.plan.accepts_assignments ? 'Yes' : 'No — closed to new assignments',
                },
              ]}
            />

            <div className="action-row">
              <Button onClick={() => setEditing(true)}>Edit limits</Button>
              <GatedAction
                label="Close to new assignments"
                allowed={data.plan.accepts_assignments}
                // The server's own condition, restated only because this
                // endpoint returns no `can_*` field: closing a closed plan is
                // idempotent, so the disabled state here is a courtesy rather
                // than a rule, and it says so.
                reason={
                  data.plan.accepts_assignments
                    ? null
                    : 'This plan is already closed. Its existing tenants keep it.'
                }
                variant="secondary"
                onClick={() => setClosing(true)}
              />
            </div>

            <h2 className="eyebrow">Tenants on this plan</h2>
            {data.tenants.length === 0 ? (
              <p className="gated__reason">
                No tenants. A plan with no tenants can be edited without consequence — which is
                the only time that is true.
              </p>
            ) : (
              <Table
                caption="Assigned tenants"
                columns={[
                  {
                    key: 'name',
                    header: 'Tenant',
                    cell: (row: S['AssignedTenantBody']) => (
                      <Link to={`/admin/tenants/${row.tenant_id}`}>{row.tenant_name}</Link>
                    ),
                  },
                  {
                    key: 'code',
                    header: 'Code',
                    cell: (row: S['AssignedTenantBody']) => <code>{row.tenant_code}</code>,
                  },
                ]}
                rows={data.tenants}
                rowKey={(row) => row.tenant_id}
              />
            )}

            {editing ? (
              <EditDialog plan={data.plan} onClose={() => setEditing(false)} />
            ) : null}
            {closing ? (
              <CloseDialog plan={data.plan} onClose={() => setClosing(false)} />
            ) : null}
          </>
        )}
      </QueryState>
    </div>
  );
}

// ----------------------------------------------------------------- dialogs

type Limits = Record<LimitKey, string>;

function limitsFrom(plan?: PlanBody): Limits {
  return Object.fromEntries(
    LIMIT_FIELDS.map((field) => [field.key, String(plan ? plan[field.key] : 0)]),
  ) as Limits;
}

function toBody(limits: Limits): S['PlanLimitsBody'] {
  return {
    event_limit: Number(limits.event_limit),
    recommendation_limit: Number(limits.recommendation_limit),
    training_limit: Number(limits.training_limit),
    product_limit: Number(limits.product_limit),
    storage_limit_bytes: Number(limits.storage_limit_bytes),
  };
}

/** The five limits, as five inputs. Shared so create and edit cannot drift. */
function LimitInputs({
  limits,
  fieldErrors,
  onChange,
}: {
  limits: Limits;
  fieldErrors: Record<string, string | undefined>;
  onChange: (key: LimitKey, value: string) => void;
}) {
  return (
    <>
      {LIMIT_FIELDS.map((field) => (
        <Input
          key={field.key}
          label={field.label}
          type="number"
          min={0}
          value={limits[field.key]}
          error={fieldErrors[field.key]}
          onChange={(event) => onChange(field.key, event.target.value)}
          hint={field.hint}
        />
      ))}
    </>
  );
}

function CreateDialog({ onClose }: { onClose: () => void }) {
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [limits, setLimits] = useState<Limits>(() => limitsFrom());
  const mutation = usePlatformMutation(createPlan);
  const form = useSubmit(mutation.mutateAsync, onClose);

  return (
    <Dialog
      title="Create plan"
      onClose={onClose}
      confirmLabel="Create"
      confirmDisabled={code.trim() === '' || name.trim() === ''}
      busy={form.pending}
      onConfirm={() =>
        form.submit({
          plan_code: code.trim(),
          plan_name: name.trim(),
          description: description.trim() === '' ? null : description.trim(),
          limits: toBody(limits),
          service_limits: {},
        })
      }
      wide
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <Input
        label="Code"
        required
        value={code}
        error={form.fieldErrors.plan_code}
        onChange={(event) => setCode(event.target.value)}
        hint="Short, stable, and quoted in support conversations. It cannot be changed afterwards."
      />
      <Input
        label="Name"
        required
        value={name}
        error={form.fieldErrors.plan_name}
        onChange={(event) => setName(event.target.value)}
      />
      <Textarea
        label="Description"
        value={description}
        error={form.fieldErrors.description}
        onChange={(event) => setDescription(event.target.value)}
      />
      <LimitInputs
        limits={limits}
        fieldErrors={form.fieldErrors}
        onChange={(key, value) => setLimits((current) => ({ ...current, [key]: value }))}
      />
    </Dialog>
  );
}

function EditDialog({ plan, onClose }: { plan: PlanBody; onClose: () => void }) {
  const [name, setName] = useState(plan.plan_name);
  const [limits, setLimits] = useState<Limits>(() => limitsFrom(plan));
  const mutation = usePlatformMutation((body: S['UpdatePlanRequest']) =>
    updatePlan(plan.plan_id, body),
  );
  const form = useSubmit(mutation.mutateAsync, onClose);

  return (
    <Dialog
      title={`Edit ${plan.plan_name}`}
      onClose={onClose}
      confirmLabel="Save"
      busy={form.pending}
      onConfirm={() => form.submit({ plan_name: name.trim(), limits: toBody(limits) })}
      wide
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <Banner kind="warning">
        {plan.assigned_tenants === 0
          ? 'No tenants are on this plan yet.'
          : `${plan.assigned_tenants} tenant${plan.assigned_tenants === 1 ? '' : 's'} are on this plan. A lowered limit applies to them from the next enforcement, not retroactively.`}
      </Banner>
      <Input
        label="Name"
        required
        value={name}
        error={form.fieldErrors.plan_name}
        onChange={(event) => setName(event.target.value)}
      />
      <LimitInputs
        limits={limits}
        fieldErrors={form.fieldErrors}
        onChange={(key, value) => setLimits((current) => ({ ...current, [key]: value }))}
      />
    </Dialog>
  );
}

function CloseDialog({ plan, onClose }: { plan: PlanBody; onClose: () => void }) {
  const mutation = usePlatformMutation(() => closePlan(plan.plan_id));
  const form = useSubmit<PlanBody>(() => mutation.mutateAsync(undefined), onClose);

  return (
    <Dialog
      title={`Close ${plan.plan_name}`}
      onClose={onClose}
      confirmLabel="Close plan"
      confirmVariant="danger"
      busy={form.pending}
      onConfirm={() => form.submit(undefined)}
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <p>
        No new tenant can be assigned to this plan. The {plan.assigned_tenants} already on it keep
        it, keep its limits, and are not moved or notified — closing a plan is a decision about
        sales, not about service.
      </p>
    </Dialog>
  );
}
