import { Banner, Cell, PanelTable } from './primitives';

type Scores = Record<string, unknown> & { examples?: number; unknown_targets?: number };
export interface Comparison {
  protocol: string;
  examples: number;
  candidate: Scores;
  popularity_baseline: Scores;
  active: (Scores & { model_version_id: string | null; unavailable_reason?: string }) | null;
}

const MEASURES = ['Hit@1', 'Hit@10', 'NDCG@10', 'MRR@10', 'catalog_coverage@10'];
const label = (key: string) => key === 'catalog_coverage@10' ? 'Catalog coverage@10' : key;

export function comparisonOf(metrics: unknown): Comparison | null {
  const value = (metrics as { comparison?: unknown } | null)?.comparison;
  return value && typeof value === 'object' && 'candidate' in value ? value as Comparison : null;
}

/** XR-F-10: every column is scored on the same examples, so differences are meaningful. */
export function CommonComparison({ comparison, activeLabel }: { comparison: Comparison; activeLabel?: string }) {
  const active = comparison.active && !comparison.active.unavailable_reason ? comparison.active : null;
  const columns = [
    { key: 'candidate', label: 'This version', scores: comparison.candidate },
    ...(active ? [{ key: 'active', label: `Active then${activeLabel ? ` (${activeLabel})` : ''}`, scores: active as Scores }] : []),
    { key: 'baseline', label: 'Popularity baseline', scores: comparison.popularity_baseline },
  ];
  const num = (s: Scores, k: string) => typeof s[k] === 'number' ? s[k] as number : null;
  return <>
    {comparison.active?.unavailable_reason ? <Banner tone="warn" title="The active version could not be scored">{comparison.active.unavailable_reason}</Banner> : null}
    <PanelTable columns={['Measure', ...columns.map(c => ({ label: c.label, align: 'right' as const })), ...(active ? [{ label: 'Difference', align: 'right' as const }] : [])]}
      rows={[...MEASURES.map(key => {
        const mine = num(comparison.candidate, key);
        const theirs = active ? num(active as Scores, key) : null;
        const diff = mine !== null && theirs !== null ? mine - theirs : null;
        return <tr key={key}><Cell>{label(key)}</Cell>
          {columns.map(c => <td key={c.key} className="num">{num(c.scores, key)?.toFixed(4) ?? '—'}</td>)}
          {active ? <td className={`num${diff ? diff > 0 ? ' pos' : ' neg' : ''}`}>{diff === null ? '—' : Math.abs(diff) < 5e-5 ? 'Same' : `${diff > 0 ? '+' : ''}${diff.toFixed(4)}`}</td> : null}
        </tr>;
      }), <tr key="unknown"><Cell>Targets the version does not know</Cell>
        {columns.map(c => <td key={c.key} className="num">{num(c.scores, 'unknown_targets') ?? 0}</td>)}{active ? <td /> : null}</tr>]} />
  </>;
}
