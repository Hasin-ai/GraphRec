import { FormEvent, useState } from "react";
import { login } from "../api/auth";
import { GraphRecApiError } from "../api/types";
import { setAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { navigate, safeReturnTo } from "../navigation";

function safeErrorMessage(error: unknown): string {
  if (!(error instanceof GraphRecApiError)) {
    return "Sign-in is temporarily unavailable. Try again shortly.";
  }
  if (error.code === "authentication_failed") {
    return "The supplied credentials could not be authenticated.";
  }
  if (error.code === "rate_limit_exceeded") {
    return `Too many sign-in attempts. Try again in ${error.retryAfterSeconds ?? "a few"} seconds.`;
  }
  return error.message;
}

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const reason = new URLSearchParams(window.location.search).get("reason");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const session = await login({ email: email.trim().toLowerCase(), password });
      setAuthSession(session);
      navigate(safeReturnTo(new URLSearchParams(window.location.search).get("returnTo")));
    } catch (caught) {
      setError(caught);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-shell">
      <header className="auth-header">
        <Brand />
        <a className="text-link" href="/auth/register">
          Register a tenant
        </a>
      </header>
      <div className="auth-layout login-layout">
        <section className="auth-intro">
          <p className="eyebrow">Tenant sign-in</p>
          <h1>Return to your isolated GraphRec workspace.</h1>
          <p className="lede compact">
            Tenant identity and permissions come from the authenticated account. No tenant selector is accepted.
          </p>
          <ol className="step-list" aria-label="Sign-in protections">
            <li>Argon2id password verification</li>
            <li>Short-lived scoped access token</li>
            <li>Revocable refresh credential stored only as a hash</li>
          </ol>
        </section>
        <section className="auth-card" aria-labelledby="login-heading">
          <p className="breadcrumb">
            <a href="/">Home</a> <span aria-hidden="true">/</span> Sign in
          </p>
          <h2 id="login-heading">Sign in</h2>
          <p className="form-note">Use an active account already provisioned for a tenant.</p>
          {reason === "expired" ? (
            <div className="pending-panel" role="status">
              Your session expired. Sign in again to continue.
            </div>
          ) : null}
          <form onSubmit={handleSubmit}>
            <label htmlFor="login-email">Email</label>
            <input
              id="login-email"
              name="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              disabled={isSubmitting}
              placeholder="admin@example.org"
            />
            <label htmlFor="login-password">Password</label>
            <input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              disabled={isSubmitting}
            />
            {error ? (
              <div className="error-panel" role="alert">
                <strong>Sign-in was not completed</strong>
                <p>{safeErrorMessage(error)}</p>
                {error instanceof GraphRecApiError && error.correlationId ? (
                  <small>Reference: {error.correlationId}</small>
                ) : null}
              </div>
            ) : null}
            <button className="button primary full" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Authenticating…" : "Sign in"}
            </button>
            <button
              className="button secondary full"
              type="button"
              onClick={() => {
                setEmail("demo-admin@example.org");
                setPassword("local-demo-password-change-me");
              }}
              style={{ marginTop: "0.5rem" }}
            >
              Fill Demo Administrator Credentials
            </button>
          </form>
          <p className="auth-footnote">
            <a className="text-link" href="/auth/recover">
              Forgot your password?
            </a>
          </p>
        </section>
      </div>
    </main>
  );
}
