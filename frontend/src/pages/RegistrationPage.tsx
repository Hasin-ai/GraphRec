import { FormEvent, useRef, useState } from "react";
import { registerTenant } from "../api/tenants";
import { GraphRecApiError, type TenantRegistrationResult } from "../api/types";
import { Brand } from "../components/Brand";

interface OperationIdentity {
  fingerprint: string;
  key: string;
}

function safeErrorMessage(error: unknown): string {
  if (!(error instanceof GraphRecApiError)) {
    return "Registration is temporarily unavailable. Keep this page open and try again.";
  }
  if (error.code === "duplicate_resource") {
    return "This registration cannot be completed with the supplied information.";
  }
  if (error.code === "idempotency_conflict") {
    return "The registration details changed during submission. Review them and submit again.";
  }
  if (error.code === "rate_limit_exceeded") {
    return `Too many registration attempts. Try again in ${error.retryAfterSeconds ?? "a few"} seconds.`;
  }
  return error.message;
}

export function RegistrationPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<TenantRegistrationResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const operation = useRef<OperationIdentity | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = { name: name.trim().replace(/\s+/g, " "), admin_email: email.trim().toLowerCase() };
    const fingerprint = JSON.stringify(input);
    if (operation.current?.fingerprint !== fingerprint) {
      operation.current = { fingerprint, key: crypto.randomUUID() };
    }

    setIsSubmitting(true);
    setError(null);
    try {
      setResult(await registerTenant(input, operation.current.key));
    } catch (caught) {
      setError(caught);
    } finally {
      setIsSubmitting(false);
    }
  }

  if (result) {
    return (
      <main className="auth-shell">
        <header className="auth-header">
          <Brand />
        </header>
        <section className="auth-card success-card" aria-labelledby="registration-complete">
          <div className="success-symbol" aria-hidden="true">
            ✓
          </div>
          <p className="eyebrow">Tenant registered</p>
          <h1 id="registration-complete">{result.name} has an isolated GraphRec workspace.</h1>
          <p className="lede compact">
            The initial administrator identity is <strong>{result.administrator_email}</strong>.
          </p>
          <div className="status-panel">
            <span className="status-dot" aria-hidden="true" />
            Tenant status: {result.status}
          </div>
          <div className="pending-panel">
            <strong>Account setup is API pending</strong>
            <p>{result.next_step}</p>
            <p>Establish a password below to immediately open your isolated workspace.</p>
          </div>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const formEl = e.currentTarget;
              const pwdInput = formEl.querySelector<HTMLInputElement>("input[name='setup_password']");
              const pwd = pwdInput?.value;
              if (!pwd || pwd.length < 8) return;
              try {
                const { setupPassword } = await import("../api/auth");
                const { setAuthSession } = await import("../auth/session");
                const { navigate } = await import("../navigation");
                const session = await setupPassword({ email: result.administrator_email, password: pwd });
                setAuthSession(session);
                navigate("/app");
              } catch (err: unknown) {
                alert(err instanceof Error ? err.message : "Password setup failed");
              }
            }}
            style={{ marginTop: "1rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}
          >
            <label htmlFor="setup-pwd-input">Create Credential Passcode for {result.administrator_email}</label>
            <input
              id="setup-pwd-input"
              name="setup_password"
              type="password"
              minLength={8}
              required
              placeholder="Minimum 8 characters"
              defaultValue="NorthwindPass123!"
              style={{ padding: "0.6rem", borderRadius: "0.6rem", border: "1px solid var(--line)" }}
            />
            <button className="button primary full" type="submit">
              Set Credential Passcode & Open Workspace (/app)
            </button>
          </form>
          <div style={{ marginTop: "0.75rem" }}>
            <a className="button secondary full" href="/auth/login">
              Sign In with Existing Password
            </a>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="auth-shell">
      <header className="auth-header">
        <Brand />
        <a className="text-link" href="/auth/login">
          Already registered?
        </a>
      </header>
      <div className="auth-layout">
        <section className="auth-intro">
          <p className="eyebrow">Create your tenant</p>
          <h1>Start with a clean, isolated business workspace.</h1>
          <p className="lede compact">
            This first working path creates only what the approved API contract supports.
          </p>
          <ol className="step-list" aria-label="Registration outcomes">
            <li>Tenant and invited administrator identity</li>
            <li>Free demonstration plan and quotas</li>
            <li>Redacted audit history and replay protection</li>
          </ol>
        </section>
        <section className="auth-card" aria-labelledby="registration-heading">
          <p className="breadcrumb">
            <a href="/">Home</a> <span aria-hidden="true">/</span> Register
          </p>
          <h2 id="registration-heading">Tenant registration</h2>
          <p className="form-note">No payment, tenant ID, contact profile, or password is requested.</p>
          <form onSubmit={handleSubmit}>
            <label htmlFor="tenant-name">Business name</label>
            <input
              id="tenant-name"
              name="name"
              autoComplete="organization"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={200}
              required
              disabled={isSubmitting}
              placeholder="Northwind Shop"
            />
            <label htmlFor="admin-email">Administrator email</label>
            <input
              id="admin-email"
              name="admin_email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              disabled={isSubmitting}
              placeholder="admin@northwind.example"
            />
            {error ? (
              <div className="error-panel" role="alert">
                <strong>Registration was not completed</strong>
                <p>{safeErrorMessage(error)}</p>
                {error instanceof GraphRecApiError && error.correlationId ? (
                  <small>Reference: {error.correlationId}</small>
                ) : null}
              </div>
            ) : null}
            <button className="button primary full" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Creating isolated tenant…" : "Register tenant"}
            </button>
          </form>
          <p className="privacy-note">
            Submission creates durable records. Repeated network retries reuse the same operation key.
          </p>
        </section>
      </div>
    </main>
  );
}
