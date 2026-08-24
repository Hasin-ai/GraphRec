/**
 * The state pill. §11: state is a `Badge`, never plain text.
 *
 * The tone is not chosen by the caller from a colour vocabulary; it is looked
 * up in `BADGE_TONES`, which is generated from the prototype by
 * `scripts/gen_enums.py`. That is the whole point — the mapping from a job
 * state to a colour is a product decision recorded in one place, and a caller
 * that wants to render `DeploymentState.STOPPED` names the domain, not the
 * colour it happens to be today.
 */
import { BADGE_TONES } from '../lib/enums';
import type { BadgeTone } from '../lib/enums';

export type BadgeDomain = keyof typeof BADGE_TONES;

export interface BadgeProps {
  /** Which generated map to read: `job`, `model`, `deploy`, `tenant`, … */
  domain: BadgeDomain;
  /** The enum value, e.g. `succeeded`. */
  value: string;
  /** Overrides the label; the value itself is used when absent. */
  label?: string;
}

const FALLBACK: BadgeTone = 'neu';

export function Badge({ domain, value, label }: BadgeProps) {
  const map = BADGE_TONES[domain] as Record<string, BadgeTone | undefined>;
  const tone = map[value] ?? FALLBACK;
  return (
    <span className={`badge badge--${tone}`} data-value={value}>
      {label ?? value.replace(/_/g, ' ')}
    </span>
  );
}

/** For the handful of places that carry a tone but no domain enum. */
export function ToneBadge({ tone, children }: { tone: BadgeTone; children: string }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}
