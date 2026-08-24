/**
 * Gate 5, rendered.
 *
 * §10.4 is emphatic that gate 5 is not a guard: it never navigates and never
 * hides anything. A resource that is in the wrong state for an action shows the
 * action, disabled, with **the server's own reason** beside it. So this file
 * has exactly one rule in it, and every page that acts on a resource uses it:
 *
 *   the control's enabled state and the sentence explaining it both come from
 *   the response, never from a condition written here.
 *
 * The reason is attached with `aria-describedby` rather than `title`, because a
 * `title` is invisible to a keyboard user and to a screen reader that is not
 * hovering — and the population most affected by a disabled button is exactly
 * the one that cannot hover.
 */

import { useId } from 'react';
import type { ReactNode } from 'react';
import { Button } from '../ui';
import type { ButtonVariant } from '../ui';

export interface GatedActionProps {
  label: string;
  /** The server's field: `can_cancel`, `actions.activate.allowed`, and so on. */
  allowed: boolean;
  /** The server's sentence. Required whenever `allowed` is false. */
  reason?: string | null;
  variant?: ButtonVariant;
  /** In flight. Kept separate from `allowed` so a slow request does not read
      as a refusal — a disabled-because-busy button has no reason to give. */
  busy?: boolean;
  onClick: () => void;
}

export function GatedAction({
  label,
  allowed,
  reason,
  variant = 'secondary',
  busy = false,
  onClick,
}: GatedActionProps) {
  const reasonId = useId();
  const explained = !allowed && reason;

  return (
    <span className="gated">
      <Button
        variant={variant}
        disabled={!allowed || busy}
        onClick={onClick}
        aria-describedby={explained ? reasonId : undefined}
      >
        {label}
      </Button>
      {explained ? (
        <span className="gated__reason" id={reasonId}>
          {reason}
        </span>
      ) : null}
    </span>
  );
}

/**
 * A sentence the server supplied about why something is the way it is.
 *
 * Used for `ineligibility` on a product and `blocked_reason` on a job — the
 * cases where there is no control to disable, only a fact to state.
 */
export function ServerReason({ children }: { children: ReactNode }) {
  return <p className="serverreason">{children}</p>;
}
