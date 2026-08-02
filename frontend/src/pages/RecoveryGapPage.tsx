import { Brand } from "../components/Brand";

export function RecoveryGapPage() {
  return (
    <main className="auth-shell">
      <header className="auth-header">
        <Brand />
      </header>
      <section className="auth-card gap-card">
        <p className="eyebrow">Contract gap</p>
        <h1>Password recovery is not enabled.</h1>
        <p>
          The approved API contract does not define recovery endpoints or verification rules. No recovery data is
          collected until that contract is approved.
        </p>
        <a className="button primary full" href="/auth/login">
          Return to sign in
        </a>
      </section>
    </main>
  );
}
