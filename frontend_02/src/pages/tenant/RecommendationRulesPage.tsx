import { useEffect, useState } from "react";
import { recommendationRules } from "../../api";
import { describeError } from "../../api/client";
import type { RecommendationPolicy } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime } from "../../lib/format";
import { Field, Form, TextInput, type FormError } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Banner, DefinitionList, ErrorBanner, Panel, Skeleton } from "../../ui/primitives";
import { parseBounded } from "./RetrainingPolicyPanel";

interface Draft { diversity: boolean; maxPer: string; freshness: boolean; weight: string; halfLife: string }
const toDraft = (p: RecommendationPolicy): Draft => ({ diversity: p.diversity_enabled, maxPer: String(p.max_per_category), freshness: p.freshness_enabled, weight: String(p.freshness_weight), halfLife: String(p.freshness_half_life_days) });

export function parseWeight(value: string): number | string {
  const n = Number(value.trim());
  if (!value.trim() || !Number.isFinite(n)) return "Enter a number.";
  if (n < 0 || n > 0.3) return "Enter a weight from 0 to 0.3.";
  return n;
}

/** XR-F-04 / XR-NF-02: bounded, versioned diversity and freshness rules. */
export function RecommendationRulesPage() {
  const { can } = useSession();
  const { flash } = useToast();
  const policy = useResource(() => recommendationRules.get(), []);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);
  const writable = can("models:deploy");
  const p = policy.data && typeof policy.data.diversity_enabled === "boolean" ? policy.data : null;
  useEffect(() => { if (p && !draft) setDraft(toDraft(p)); }, [p, draft]);

  async function save() {
    if (!draft) return;
    const maxPer = parseBounded(draft.maxPer, 1, 100);
    const weight = parseWeight(draft.weight);
    const halfLife = parseBounded(draft.halfLife, 1, 3650);
    const next: Record<string, string> = {};
    if (typeof maxPer === "string") next.maxPer = maxPer;
    if (typeof weight === "string") next.weight = weight;
    if (typeof halfLife === "string") next.halfLife = halfLife;
    setErrors(next);
    if (Object.keys(next).length) { setFormError({ title: "Check the highlighted fields", body: "The rules were not saved." }); return; }
    setBusy(true); setFormError(null);
    try {
      const saved = await recommendationRules.put({ diversity_enabled: draft.diversity, max_per_category: maxPer as number, freshness_enabled: draft.freshness, freshness_weight: weight as number, freshness_half_life_days: halfLife as number });
      setDraft(toDraft(saved)); await policy.reload(); flash(`Recommendation rules saved as version ${saved.version}.`);
    } catch (error) { setFormError({ title: "The rules could not be saved", body: describeError(error) }); }
    finally { setBusy(false); }
  }

  return <Page crumbs={[{ label: "Home", to: "/home" }, { label: "Recommendation Rules" }]} kicker="Serving" title="Recommendation Rules"
    subtitle="Diversity and freshness adjustments applied after relevance ranking." actions={[{ label: "Refresh", onClick: () => { setDraft(null); void policy.reload(); } }]}>
    {policy.error ? <ErrorBanner error={policy.error} onRetry={policy.reload} /> : null}
    <Banner tone="info" title="Bounded and explainable">Rules only reorder eligible products after exclusions; they never add products. Freshness can move an item up by at most about 43% of the relevance range at the maximum weight (0.3). Every response that used rules reports the version it applied.</Banner>
    {!p ? (policy.loading ? <Skeleton rows={3} /> : null) : <Panel title="Current rules" note={p.configured ? `Version ${p.version}` : "Not configured — relevance order only"}>
      <DefinitionList items={[
        { label: "Diversity", value: p.diversity_enabled ? `At most ${p.max_per_category} per category` : "Off" },
        { label: "Freshness", value: p.freshness_enabled ? `Weight ${p.freshness_weight}, half-life ${p.freshness_half_life_days} days` : "Off" },
        { label: "Last changed", value: fmtDateTime(p.updated_at) },
      ]} />
      {writable && draft ? <Form onSubmit={save} busy={busy} error={formError} submitLabel="Save rules">
        <Field id="rr-diversity" label="Category diversity"><label className="check"><input id="rr-diversity" type="checkbox" checked={draft.diversity} onChange={e => setDraft({ ...draft, diversity: e.target.checked })} /> Limit how many items share one category</label></Field>
        <Field id="rr-max" label="Maximum items per category" error={errors.maxPer} hint="1 to 100. Relaxed in relevance order if the list would otherwise be short.">
          <TextInput id="rr-max" value={draft.maxPer} onChange={v => setDraft({ ...draft, maxPer: v })} mono />
        </Field>
        <Field id="rr-freshness" label="Freshness boost"><label className="check"><input id="rr-freshness" type="checkbox" checked={draft.freshness} onChange={e => setDraft({ ...draft, freshness: e.target.checked })} /> Boost recently added products</label></Field>
        <Field id="rr-weight" label="Freshness weight" error={errors.weight} hint="0 to 0.3.">
          <TextInput id="rr-weight" value={draft.weight} onChange={v => setDraft({ ...draft, weight: v })} mono />
        </Field>
        <Field id="rr-half" label="Freshness half-life (days)" error={errors.halfLife} hint="Age at which the boost halves. 1 to 3650.">
          <TextInput id="rr-half" value={draft.halfLife} onChange={v => setDraft({ ...draft, halfLife: v })} mono />
        </Field>
      </Form> : !writable ? <p className="footnote">Changing rules requires models:deploy (tenant administrators).</p> : null}
    </Panel>}
  </Page>;
}
