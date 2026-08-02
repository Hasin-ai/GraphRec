import { Brand } from "../components/Brand";
import { SpaLink } from "../components/SpaLink";

export function UnauthorizedPage() {
  return (
    <main className="centered-page protected-gap">
      <Brand />
      <p className="eyebrow">401 Unauthorized</p>
      <h1>Authentication Required</h1>
      <p className="lede compact">Your session has expired or authentication credentials are missing.</p>
      <a className="button primary" href="/auth/login">
        Sign In to Continue
      </a>
    </main>
  );
}

export function ForbiddenPage() {
  return (
    <main className="centered-page protected-gap">
      <Brand />
      <p className="eyebrow">403 Forbidden</p>
      <h1>Insufficient Permissions</h1>
      <p className="lede compact">Your current identity does not possess the required authorization scope for this resource.</p>
      <SpaLink className="button primary" href="/app">
        Return to Workspace
      </SpaLink>
    </main>
  );
}

export function ServiceUnavailablePage() {
  return (
    <main className="centered-page protected-gap">
      <Brand />
      <p className="eyebrow">503 Service Unavailable</p>
      <h1>Temporary Failure</h1>
      <p className="lede compact">The GraphRec cluster is experiencing temporary maintenance or high load. Please try again shortly.</p>
      <button className="button primary" onClick={() => window.location.reload()}>
        Retry Request
      </button>
    </main>
  );
}

export function ResetResultPage() {
  return (
    <main className="centered-page protected-gap">
      <Brand />
      <p className="eyebrow">Account Recovery</p>
      <h1>Recovery Outcome</h1>
      <p className="lede compact">Password reset processing is feature-gated pending security proof verification.</p>
      <a className="button primary" href="/auth/login">
        Back to Sign In
      </a>
    </main>
  );
}
