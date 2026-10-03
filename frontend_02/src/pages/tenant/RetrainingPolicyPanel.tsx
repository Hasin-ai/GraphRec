import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { retraining } from "../../api";
import { describeError } from "../../api/client";
import type { RetrainingPolicy } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime, fmtNumber, humanize } from "../../lib/format";
import { Field, Form, TextInput, type FormError } from "../../ui/Form";
import { DefinitionList, ErrorBanner, Panel, Skeleton } from "../../ui/primitives";

interface Draft { schedule: boolean; interval: string; events: boolean; threshold: string; epochs: string }
const toDraft = (p: RetrainingPolicy): Draft => ({ schedule: p.schedule_enabled, interval: String(p.interval_minutes), events: p.event_trigger_enabled, threshold: String(p.event_threshold), epochs: String(p.epochs) });

/** Parses a whole number within [min, max]; returns an error message otherwise. */
export function parseBounded(value: string, min: number, max: number): number | string {
  if (!/^\d+$/.test(value.trim())) return "Enter a whole number.";
  const n = Number(value);
  if (n < min || n > max) return `Enter a value from ${fmtNumber(min)} to ${fmtNumber(max)}.`;
  return n;
}

/** XR-F-02 / XR-F-03: scheduled and event-triggered retraining settings. */
export function RetrainingPolicyPanel() {
  const { can } = useSession();
  const { flash } = useToast();
  const policy = useResource(() => retraining.get(), []);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);
  const writable = can("training:write");
  // Ignore malformed payloads rather than rendering partial state.
  const p = policy.data && typeof policy.data.schedule_enabled === "boolean" ? policy.data : null;
  useEffect(() => { if (p && !draft) setDraft(toDraft(p)); }, [p, draft]);

  async function save() {
    if (!draft || !p) return;
    const interval = parseBounded(draft.interval, p.minimum_interval_minutes, 43200);
    const threshold = parseBounded(draft.threshold, 1, 10_000_000);
    const epochs = parseBounded(draft.epochs, 1, 10);
    const next: Record<string, string> = {};
    if (typeof interval === "string") next.interval = interval;
    if (typeof threshold === "string") next.threshold = threshold;
    if (typeof epochs === "string") next.epochs = epochs;
    setErrors(next);
    if (Object.keys(next).length) { setFormError({ title: "Check the highlighted fields", body: "The policy was not saved." }); return; }
    setBusy(true); setFormError(null);
    try {
      const saved = await retraining.put({ schedule_enabled: draft.schedule, interval_minutes: interval as number, event_trigger_enabled: draft.events, event_threshold: threshold as number, epochs: epochs as number });
      setDraft(toDraft(saved)); await policy.reload(); flash("Retraining policy saved.");
    } catch (error) { setFormError({ title: "The policy could not be saved", body: describeError(error) }); }
    finally { setBusy(false); }
  }

  return <Panel title="Automatic retraining" note="Scheduled or event-triggered"
    body="New versions are registered as eligible. Activation stays a separate step. Automatic runs obey the same cooldown, quota and one-job-at-a-time rules as manual training.">
    {policy.error ? <ErrorBanner error={policy.error} title="Retraining policy unavailable" onRetry={policy.reload} /> : null}
    {!p ? (policy.loading ? <Skeleton rows={3} /> : null) : <>
      <DefinitionList items={[
        { label: "Next scheduled run", value: p.schedule_enabled ? fmtDateTime(p.next_run_at) : "Schedule off" },
        { label: "New events since last training", value: `${fmtNumber(p.new_events_since_last_training)}${p.event_trigger_enabled ? ` of ${fmtNumber(p.event_threshold)}` : ""}` },
        { label: "Last automatic outcome", value: p.last_outcome ? `${humanize(p.last_outcome)}${p.last_trigger ? ` · ${p.last_trigger}` : ""} · ${fmtDateTime(p.last_outcome_at)}` : "None yet" },
        { label: "Last automatic run", value: p.last_job_id ? <Link to={`/training/${p.last_job_id}`}>View run</Link> : "None yet" },
        { label: "Training in progress", value: p.training_in_progress ? "Yes — triggers wait" : "No" },
      ]} />
      {p.last_outcome_detail ? <p className="footnote">{p.last_outcome_detail}</p> : null}
      {writable && draft ? <Form onSubmit={save} busy={busy} error={formError} submitLabel="Save policy" note={JSON.stringify(draft) === JSON.stringify(toDraft(p)) ? (p.configured ? `Saved · last changed ${fmtDateTime(p.updated_at)}` : "Not configured yet") : "● Unsaved changes"}>
        <Field id="rt-schedule" label="Scheduled retraining" wide>
          <label className="switch"><input id="rt-schedule" type="checkbox" checked={draft.schedule} onChange={e => setDraft({ ...draft, schedule: e.target.checked })} /><span className="track" aria-hidden="true" />{draft.schedule ? "On: retrain on a fixed interval" : "Off"}</label>
        </Field>
        <Field id="rt-interval" label="Interval (minutes)" error={errors.interval} hint={`Minimum ${fmtNumber(p.minimum_interval_minutes)} minutes; 1440 = daily.`}>
          <TextInput id="rt-interval" type="number" value={draft.interval} onChange={v => setDraft({ ...draft, interval: v })} disabled={!draft.schedule} />
        </Field>
        <Field id="rt-events" label="Event-triggered retraining" wide>
          <label className="switch"><input id="rt-events" type="checkbox" checked={draft.events} onChange={e => setDraft({ ...draft, events: e.target.checked })} /><span className="track" aria-hidden="true" />{draft.events ? "On: retrain after enough new accepted events" : "Off"}</label>
        </Field>
        <Field id="rt-threshold" label="New-event threshold" error={errors.threshold} hint="Counted since the latest training run started.">
          <TextInput id="rt-threshold" type="number" value={draft.threshold} onChange={v => setDraft({ ...draft, threshold: v })} disabled={!draft.events} />
        </Field>
        <Field id="rt-epochs" label="Epochs per automatic run" error={errors.epochs} hint="1 to 10. Used by both triggers.">
          <TextInput id="rt-epochs" type="number" value={draft.epochs} onChange={v => setDraft({ ...draft, epochs: v })} disabled={!draft.schedule && !draft.events} />
        </Field>
      </Form> : <p className="footnote">{writable ? "Loading…" : "Only tenant administrators can change the retraining policy."}</p>}
    </>}
  </Panel>;
}
