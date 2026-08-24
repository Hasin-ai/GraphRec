import type { ReactNode } from 'react';

export interface FilterBarProps {
  children: ReactNode;
  /** Cleared filters are a distinct action from an empty one, so it is offered. */
  onReset?: () => void;
}

export function FilterBar({ children, onReset }: FilterBarProps) {
  return (
    <form
      className="filterbar"
      role="search"
      onSubmit={(event) => event.preventDefault()}
      aria-label="Filters"
    >
      {children}
      {onReset ? (
        <button type="button" className="btn btn--ghost btn--sm" onClick={onReset}>
          Clear filters
        </button>
      ) : null}
    </form>
  );
}
