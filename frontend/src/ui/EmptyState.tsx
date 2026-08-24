import type { ReactNode } from 'react';

export interface EmptyStateProps {
  /** Names the thing: "No model versions yet." */
  headline: string;
  /** One sentence offering the next step. */
  body: string;
  action?: ReactNode;
}

/** Icon-free by instruction (§11): headline, one sentence, primary action. */
export function EmptyState({ headline, body, action }: EmptyStateProps) {
  return (
    <div className="empty">
      <div className="empty__headline">{headline}</div>
      <div className="empty__body">{body}</div>
      {action}
    </div>
  );
}
