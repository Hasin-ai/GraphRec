import { Cell, PanelTable } from './primitives';

/** Compare the recorded evaluation splits without mixing artifact metadata into quality. */
export function QualitySummary({ metrics }: { metrics: Record<string, unknown> }) {
  const groups = [['validation', 'Validation'], ['test', 'Test'], ['popularity_baseline', 'Popularity baseline']]
    .filter(([key]) => metrics[key] && typeof metrics[key] === 'object')
    .map(([key, label]) => ({ label, values: metrics[key] as Record<string, unknown> }));
  if (!groups.length) groups.push({ label: 'Recorded', values: metrics });
  const measures = [...new Set(groups.flatMap(group => Object.keys(group.values).filter(key => typeof group.values[key] === 'number')))];
  const label = (key: string) => key.replace('catalog_coverage', 'Catalog coverage').replace('category_diversity', 'Category diversity').replace('examples', 'Evaluated examples').replace('@', ' @');
  return <PanelTable columns={['Measure', ...groups.map(group => ({ label: group.label, align: 'right' as const }))]}
    rows={measures.map(key => <tr key={key}><Cell>{label(key)}</Cell>{groups.map(group => {
      const value = group.values[key];
      return <Cell key={group.label} mono align="right">{typeof value === 'number' ? key.includes('examples') ? value.toLocaleString() : value.toFixed(4) : '—'}</Cell>;
    })}</tr>)} />;
}
