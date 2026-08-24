import { acceptInvitation } from '../../api/hooks/auth';
import { SetPasswordCard } from './SetPassword';

/**
 * `/invite/accept`. Moves the invited person `invited → active` by having them
 * set their own authentication material — the administrator who invited them
 * never chooses it and never sees it.
 */
export function InviteAcceptRoute() {
  return (
    <SetPasswordCard
      title="Accept your invitation"
      lede="Paste the invitation token you were sent, then choose a password. This activates your account."
      tokenLabel="Invitation token"
      action={acceptInvitation}
      submitLabel="Activate account"
      doneMessage="Your account is active. Sign in to continue."
    />
  );
}
