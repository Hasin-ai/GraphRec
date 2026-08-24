import { redirect } from 'react-router-dom';
import { hasSession } from '../api/session';

/**
 * `/` — resolve by identity: `/home`, `/admin`, or `/login`.
 *
 * "Has a session" here means "holds a refresh token for that realm", which is
 * a claim, not a verification. That is deliberate and safe: this only chooses
 * where to send the browser, and the destination's own loader runs gate 1
 * properly. A forged marker buys a redirect to a page that then refuses it.
 *
 * The tenant realm wins a tie. Both realms holding a session at once is a
 * developer's machine, and the tenant console is the one they meant.
 */
export function rootLoader(): Response {
  if (hasSession('tenant')) return redirect('/home');
  if (hasSession('platform')) return redirect('/admin');
  return redirect('/login');
}
