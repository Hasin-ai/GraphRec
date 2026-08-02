import { Brand } from "../components/Brand";

export function EntryPage() {
  return (
    <main className="entry-shell">
      <header className="entry-header">
        <Brand />
        <a className="text-link" href="/auth/login">
          Sign in
        </a>
      </header>
      <section className="entry-copy">
        <p className="eyebrow">GraphRec Platform · Vertical Paths 01–05</p>
        <h1>A tenant-safe foundation for useful recommendations.</h1>
        <p className="lede">
          Register an e-commerce business, then authenticate a provisioned account without exposing a public tenant
          selector. GraphRec derives tenant identity and scopes from the credential.
        </p>
        <div className="entry-actions">
          <a className="button primary" href="/auth/register">
            Register a tenant
          </a>
          <a className="button secondary" href="/auth/login">
            Sign in
          </a>
        </div>
        <dl className="trust-list">
          <div>
            <dt>No public tenant selector</dt>
            <dd>Tenant identity is never accepted from a registration URL or hidden field.</dd>
          </div>
          <div>
            <dt>Safe, replayable submission</dt>
            <dd>A stable idempotency key prevents duplicate durable effects.</dd>
          </div>
          <div>
            <dt>Credential-derived access</dt>
            <dd>Successful sign-in returns only the role and scopes assigned to the authenticated identity.</dd>
          </div>
        </dl>
      </section>
    </main>
  );
}
