import { useEffect, useState } from "react";
import { getSubscription } from "../api/subscriptions";
import { GraphRecApiError, type SubscriptionResult } from "../api/types";
import { clearAuthSession, getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";
import { SpaLink } from "../components/SpaLink";
import { navigate } from "../navigation";

function labelForLimit(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function formatLimit(value: number): string {
  return new Intl.NumberFormat().format(value);
}

function formatPeriod(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(value),
  );
}

function errorMessage(error: unknown): string {
  if (!(error instanceof GraphRecApiError)) {
    return "Subscription information is temporarily unavailable.";
  }
  if (error.code === "insufficient_scope") {
    return "This account does not have permission to view subscription information.";
  }
  if (error.code === "rate_limit_exceeded") {
    return `Too many refreshes. Try again in ${error.retryAfterSeconds ?? "a few"} seconds.`;
  }
  return error.message;
}

export function SubscriptionPage() {
  const session = getAuthSession();
  const [subscription, setSubscription] = useState<SubscriptionResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [refreshSequence, setRefreshSequence] = useState(0);

  useEffect(() => {
    if (!session || !session.scopes.includes("billing:read")) {
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    void getSubscription(session.access_token)
      .then((result) => {
        if (!cancelled) {
          setSubscription(result);
        }
      })
      .catch((caught: unknown) => {
        if (cancelled) {
          return;
        }
        if (
          caught instanceof GraphRecApiError &&
          (caught.code === "token_expired" || caught.code === "authentication_failed")
        ) {
          clearAuthSession();
          navigate("/auth/login?reason=expired&returnTo=%2Fapp%2Fsubscription");
          return;
        }
        setError(caught);
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [session, refreshSequence]);

  if (!session) {
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Authentication required</p>
        <h1>Sign in to view subscription limits.</h1>
        <a className="button primary" href="/auth/login?returnTo=%2Fapp%2Fsubscription">
          Sign in
        </a>
      </main>
    );
  }

  if (!session.scopes.includes("billing:read")) {
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Permission required</p>
        <h1>Subscription access is not granted.</h1>
        <p className="lede compact">This route requires the billing:read permission.</p>
        <SpaLink className="button secondary" href="/app">
          Return to workspace
        </SpaLink>
      </main>
    );
  }

  return (
    <main className="workspace-shell">
      <Navbar />
      <section className="subscription-heading">
        <div>
          <p className="eyebrow">Usage and Quotas / Subscription</p>
          <h1>Subscription and effective limits</h1>
          <p className="lede compact">
            Current tenant plan values derived from your authenticated workspace.
          </p>
        </div>
        <div className="page-actions">
          <SpaLink className="button secondary" href="/app/usage">View usage</SpaLink>
          <button
            className="button secondary"
            type="button"
            disabled={isLoading}
            onClick={() => setRefreshSequence((value) => value + 1)}
          >
            {isLoading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </section>

      {error ? (
        <div className="error-panel subscription-error" role="alert">
          <strong>Subscription could not be refreshed</strong>
          <p>{errorMessage(error)}</p>
          {error instanceof GraphRecApiError && error.correlationId ? (
            <small>Reference: {error.correlationId}</small>
          ) : null}
        </div>
      ) : null}

      {!subscription && isLoading ? (
        <section className="subscription-loading" aria-live="polite">
          Loading current plan and effective limits…
        </section>
      ) : null}

      {subscription ? (
        <>
          <section className="plan-summary" aria-labelledby="plan-heading">
            <div>
              <p className="eyebrow">Current plan</p>
              <h2 id="plan-heading">{subscription.plan_code}</h2>
            </div>
            <dl>
              <div>
                <dt>Status</dt>
                <dd><span className="status-badge">{subscription.status}</span></dd>
              </div>
              <div>
                <dt>Period</dt>
                <dd>{formatPeriod(subscription.period_start)} – {formatPeriod(subscription.period_end)}</dd>
              </div>
            </dl>
          </section>
          <section className="limits-card" aria-labelledby="limits-heading">
            <div className="limits-card-heading">
              <p className="eyebrow">Credential-scoped view</p>
              <h2 id="limits-heading">Effective limits</h2>
            </div>
            <div className="limits-table" role="table" aria-label="Effective subscription limits">
              {Object.entries(subscription.limits)
                .sort(([left], [right]) => left.localeCompare(right))
                .map(([name, value]) => (
                  <div className="limit-row" role="row" key={name}>
                    <span role="cell">{labelForLimit(name)}</span>
                    <strong role="cell">{formatLimit(value)}</strong>
                  </div>
                ))}
            </div>
          </section>
          <aside className="project-notice">
            <strong>{subscription.project_defaults ? "Project-default demonstration limits" : "Tenant limits"}</strong>
            <p>
              These values support the semester MVP. They are not a commercial offer, invoice, or payment commitment.
            </p>
          </aside>
        </>
      ) : null}
    </main>
  );
}
