import { useEffect, useState } from "react";
import { billing } from "../../api";
import type { PlanChangeRequest, PlanCode, SubscriptionResult } from "../../api/types";
import { useQueryState } from "../../hooks/useQueryState";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDate, fmtDateTime } from "../../lib/format";
import { HEADLINE_LIMITS, formatLimit, limitLabel } from "../../marketing/plans";
import { useLivePlans } from "../../marketing/useLivePlans";
import { Dialog } from "../../ui/Dialog";
import { Field, RadioGroup, TextArea } from "../../ui/Form";
import { Alert, Button } from "../../ui/kit";

/** Requests decided this recently are still worth telling the administrator about. */
const RECENT_DECISION_MS = 14 * 86_400_000;

/**
 * GraphRec takes no payments, so a plan change is a request a platform operator
 * approves. Shows the open request (with cancel), the latest recent decision and,
 * for administrators, the "Change plan" action. `?request=basic` opens the dialog
 * with that plan chosen (the pricing page links here).
 */
export function PlanRequestPanel({ plan, onPlanChanged }: { plan: SubscriptionResult | null; onPlanChanged: () => void }) {
  const { can } = useSession();
  const { flash } = useToast();
  const canRequest = can("billing:write");
  const requests = useResource(() => billing.planRequests(), []);
  const [wanted, setWanted] = useQueryState("request", "");
  const [open, setOpen] = useState(false);
  const pending = requests.data?.pending ?? null;
  const latest = requests.data?.items.find((r) => r.status !== "pending") ?? null;
  const recent = latest && latest.decided_at && Date.now() - Date.parse(latest.decided_at) < RECENT_DECISION_MS
    && latest.status !== "cancelled" ? latest : null;

  // Arriving from the pricing page with ?request=<plan>: open the dialog once data is in.
  useEffect(() => {
    if (wanted && canRequest && requests.data && plan && !pending && wanted !== plan.plan_code) setOpen(true);
  }, [wanted, canRequest, requests.data, plan, pending]);

  // An approved request changes the plan: refresh the plan card when one appears.
  useEffect(() => { if (recent?.status === "approved" && plan && recent.requested_plan_code !== plan.plan_code) onPlanChanged(); },
    [recent, plan, onPlanChanged]);

  const close = () => { setOpen(false); if (wanted) setWanted(""); };

  return <div className="plan-requests">
    {pending ? <Alert tone="info" title={`${pending.requested_plan_name} plan requested — waiting for approval`}
      action={canRequest ? <Button size="sm" onClick={async () => {
        try { await billing.cancelPlanRequest(pending.id); flash("Plan request cancelled."); await requests.reload(); }
        catch { flash("The request could not be cancelled. Refresh and try again.", "danger"); }
      }}>Cancel request</Button> : undefined}>
      Sent {fmtDateTime(pending.created_at)}. Your GraphRec platform operator reviews it; the new limits apply as soon as it is approved.
      {pending.message ? <> Your note: “{pending.message}”</> : null}
    </Alert> : recent ? <DecisionNotice request={recent} /> : null}
    {wanted && plan && wanted === plan.plan_code ? <Alert tone="info" compact>This workspace is already on the {plan.plan_code} plan.</Alert> : null}
    {canRequest && !pending ? <Button variant="primary" size="sm" onClick={() => setOpen(true)} disabled={!plan}>Change plan</Button> : null}
    {!canRequest && !pending ? <span className="muted small">Ask a workspace administrator to request a different plan.</span> : null}
    {open && plan ? <RequestDialog current={plan.plan_code} initial={(["free", "basic", "pro"] as string[]).includes(wanted) && wanted !== plan.plan_code ? wanted as PlanCode : undefined}
      onClose={close} onDone={async (r) => { close(); flash(`${r.requested_plan_name} plan requested. You'll see the decision here.`); await requests.reload(); }} /> : null}
  </div>;
}

function DecisionNotice({ request }: { request: PlanChangeRequest }) {
  const approved = request.status === "approved";
  return <Alert tone={approved ? "success" : "warning"} compact
    title={approved ? `${request.requested_plan_name} plan approved` : `${request.requested_plan_name} plan request was not approved`}>
    {request.decided_at ? `Decided ${fmtDate(request.decided_at)}.` : null}{request.decision_reason ? <> Operator's note: “{request.decision_reason}”</> : null}
    {!approved ? " You can send a new request." : null}
  </Alert>;
}

function RequestDialog({ current, initial, onClose, onDone }: { current: string; initial?: PlanCode; onClose: () => void; onDone: (r: PlanChangeRequest) => void }) {
  const { plans } = useLivePlans();
  const choices = plans.filter((p) => p.code !== current);
  const [code, setCode] = useState<PlanCode>(initial ?? choices[0]?.code ?? "basic");
  const [message, setMessage] = useState("");
  const chosen = plans.find((p) => p.code === code);
  const currentName = plans.find((p) => p.code === current)?.name ?? current;
  const downgrade = chosen && plans.findIndex((p) => p.code === code) < plans.findIndex((p) => p.code === current);
  return <Dialog width={600} title="Request a different plan" confirmLabel={`Request ${chosen?.name ?? "plan"}`}
    body={`GraphRec takes no payments. Your request goes to your platform operator, who approves or rejects it; the new limits apply immediately on approval. You are on ${currentName} now.`}
    consequence={downgrade ? "Moving to a smaller plan lowers your limits. If you store more than the new plan allows, nothing is deleted, but you cannot add more until usage drops." : undefined}
    onClose={onClose}
    onConfirm={async () => onDone(await billing.requestPlan({ plan_code: code, ...(message.trim() ? { message: message.trim() } : {}) }))}>
    <Field id="plan-request-choice" label="Plan">
      <RadioGroup name="plan-request-choice" value={code} onChange={setCode}
        options={choices.map((p) => ({ value: p.code, label: p.name, hint: HEADLINE_LIMITS.map((k) => `${formatLimit(k, p.limits[k])} ${limitLabel(k).toLowerCase()}`).join(" · ") }))} />
    </Field>
    <Field id="plan-request-message" label="Note for the operator (optional)" hint="What the workspace needs the capacity for. Up to 500 characters.">
      <TextArea id="plan-request-message" value={message} onChange={(v) => setMessage(v.slice(0, 500))} rows={3} />
    </Field>
  </Dialog>;
}
