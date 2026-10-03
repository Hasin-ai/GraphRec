import { useEffect, useState } from "react";
import { recommendationRules } from "../../api";
import { describeError } from "../../api/client";
import type { RecommendationPolicy } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime } from "../../lib/format";
import { Field, TextInput, type FormError } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Banner, ErrorBanner, Skeleton } from "../../ui/primitives";
import { parseBounded } from "./RetrainingPolicyPanel";

interface Draft { diversity: boolean; maxPer: string; freshness: boolean; weight: string; halfLife: string }
const toDraft = (p: RecommendationPolicy): Draft => ({ diversity: p.diversity_enabled, maxPer: String(p.max_per_category), freshness: p.freshness_enabled, weight: String(p.freshness_weight), halfLife: String(p.freshness_half_life_days) });

export function parseWeight(value: string): number | string {
  const n = Number(value.trim());
  if (!value.trim() || !Number.isFinite(n)) return "Enter a number.";
  if (n < 0 || n > 0.3) return "Enter a weight from 0 to 0.3.";
  return n;
}

/** Diversity and freshness rules: one card per rule, inputs live only while the rule is on (audit RR-1…RR-7). */
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
  const saved = p ? toDraft(p) : null;
  const dirty = !!draft && !!saved && JSON.stringify(draft) !== JSON.stringify(saved);

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
      const result = await recommendationRules.put({ diversity_enabled: draft.diversity, max_per_category: maxPer as number, freshness_enabled: draft.freshness, freshness_weight: weight as number, freshness_half_life_days: halfLife as number });
      policy.setData(result); setDraft(toDraft(result)); flash(`Recommendation rules saved (version ${result.version}).`);
    } catch (error) { setFormError({ title: "The rules could not be saved", body: describeError(error) }); }
    finally { setBusy(false); }
  }
  const discard = () => { if (saved) setDraft(saved); setErrors({}); setFormError(null); };
  const set = (patch: Partial<Draft>) => draft && setDraft({ ...draft, ...patch });
  const live = p ? [p.diversity_enabled ? `at most ${p.max_per_category} per category` : null, p.freshness_enabled ? `freshness boost (weight ${p.freshness_weight}, half-life ${p.freshness_half_life_days} days)` : null].filter(Boolean) : [];

  return <Page crumbs={[{ label: "Home", to: "/home" }, { label: "Recommendation Rules" }]} kicker="Serving" title="Recommendation Rules"
    subtitle="Rules reorder the products the model recommends. They never add or remove products."
    updated={p ? (p.configured ? <>Live: {live.length ? live.join(" · ") : "no rules on (relevance order)"} · version {p.version}{p.updated_at ? <> · changed {fmtDateTime(p.updated_at)}</> : null}</> : "Using relevance order only — no rules saved yet.") : null}>
    {policy.error ? <ErrorBanner error={policy.error} onRetry={policy.reload} /> : null}
    {!p || !draft ? (policy.loading ? <Skeleton rows={3} /> : null) : <form onSubmit={e => { e.preventDefault(); void save(); }} noValidate aria-busy={busy || undefined}>
      {formError ? <Banner tone="danger" title={formError.title}>{formError.body}</Banner> : null}
      {!writable ? <p className="footnote">Only tenant administrators can change rules. You can review the current settings.</p> : null}
      <fieldset disabled={!writable || busy}>
        <section className="rule-card">
          <div className="rule-head"><div><h2>Category diversity</h2><p>Limits how many recommended items can come from one category, so lists aren't dominated by a single category.</p></div>
            <label className="switch"><input id="rr-diversity" type="checkbox" checked={draft.diversity} onChange={e => set({ diversity: e.target.checked })} /><span className="track" aria-hidden="true" />{draft.diversity ? "On" : "Off"}</label></div>
          <div className="rule-body" aria-disabled={!draft.diversity}>
            <Field id="rr-max" label="Maximum items per category" error={errors.maxPer} hint="1 to 100. If a list would come up short, the limit is relaxed in relevance order.">
              <TextInput id="rr-max" type="number" min={1} max={100} value={draft.maxPer} onChange={v => set({ maxPer: v })} disabled={!draft.diversity} />
            </Field>
          </div>
        </section>
        <section className="rule-card">
          <div className="rule-head"><div><h2>Freshness boost</h2><p>Moves recently added products up. At the maximum weight an item can move up by about 43% of the relevance range.</p></div>
            <label className="switch"><input id="rr-freshness" type="checkbox" checked={draft.freshness} onChange={e => set({ freshness: e.target.checked })} /><span className="track" aria-hidden="true" />{draft.freshness ? "On" : "Off"}</label></div>
          <div className="rule-body" aria-disabled={!draft.freshness}>
            <Field id="rr-weight" label="Weight" error={errors.weight} hint="0 to 0.3. Higher favours newer products more.">
              <TextInput id="rr-weight" value={draft.weight} onChange={v => set({ weight: v })} disabled={!draft.freshness} />
            </Field>
            <Field id="rr-half" label="Half-life (days)" error={errors.halfLife} hint="1 to 3650. Age at which the boost halves.">
              <TextInput id="rr-half" type="number" min={1} max={3650} value={draft.halfLife} onChange={v => set({ halfLife: v })} disabled={!draft.freshness} />
            </Field>
          </div>
        </section>
      </fieldset>
      {writable ? <div className="save-bar">{dirty ? <span className="dirty">Unsaved changes</span> : <span className="clean">All changes saved</span>}
        <button type="button" className="btn btn-secondary" onClick={discard} disabled={!dirty || busy}>Discard</button>
        <button type="submit" className="btn btn-primary" disabled={!dirty || busy}>{busy ? "Saving…" : "Save rules"}</button></div> : null}
    </form>}
  </Page>;
}
