import type { ReactNode } from 'react';

export interface Definition {
  term: string;
  value: ReactNode;
}

/** The attribute block on every detail page (§11). */
export function DefinitionList({ items }: { items: readonly Definition[] }) {
  return (
    <dl className="deflist">
      {items.map((item) => (
        <div key={item.term} style={{ display: 'contents' }}>
          <dt className="deflist__term">{item.term}</dt>
          <dd className="deflist__value">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
