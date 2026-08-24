import type { ReactNode } from 'react';
import { Button } from './Button';

export type BannerKind = 'info' | 'success' | 'warning' | 'danger';

export interface BannerProps {
  kind: BannerKind;
  children: ReactNode;
  /** Present only where the banner is non-blocking (§11). */
  onDismiss?: () => void;
}

export function Banner({ kind, children, onDismiss }: BannerProps) {
  return (
    <div
      className={`banner banner--${kind}`}
      // A danger or warning banner is the answer to something the reader just
      // did, so it interrupts; info and success are context and do not.
      role={kind === 'danger' || kind === 'warning' ? 'alert' : 'status'}
    >
      <div className="banner__body">{children}</div>
      {onDismiss ? (
        <Button variant="ghost" size="sm" onClick={onDismiss} aria-label="Dismiss">
          ×
        </Button>
      ) : null}
    </div>
  );
}
