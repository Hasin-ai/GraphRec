import { useEffect, useState } from "react";
import { getUsage } from "../api/usage";
import { GraphRecApiError, type UsageDimension, type UsageSummaryResult } from "../api/types";
import { clearAuthSession, getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";
import { SpaLink } from "../components/SpaLink";
import { navigate } from "../navigation";

function label(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function number(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(value);
}

function date(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(value),
  );
}

function timestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

function stateFor(dimension: UsageDimension): "normal" | "near" | "exceeded" | "informational" {
  if (dimension.limit === null) return "informational";
  if (dimension.used > dimension.limit || (dimension.limit > 0 && dimension.used === dimension.limit)) {
    return "exceeded";
  }
  if (dimension.limit > 0 && dimension.used / dimension.limit >= 0.8) return "near";
  return "normal";
}

function errorMessage(error: unknown): string {
  if (!(error instanceof GraphRecApiError)) return "Usage information is temporarily unavailable.";
  if (error.code === "rate_limit_exceeded") {
    return `Too many refreshes. Try again in ${error.retryAfterSeconds ?? "a few"} seconds.`;
  }
  if (error.code === "metrics_unavailable") {
    return "Reconciled usage is temporarily unavailable. The last successful totals remain visible when available.";
  }
  return error.message;
}

export function UsagePage() {
  const session = getAuthSession();
  const [usage, setUsage] = useState<UsageSummaryResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [refreshSequence, setRefreshSequence] = useState(0);

  useEffect(() => {
    if (!session || !session.scopes.includes("usage:read")) return;
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    void getUsage(session.access_token)
      .then((result) => {
        if (!cancelled) setUsage(result);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        if (
          caught instanceof GraphRecApiError &&
          (caught.code === "token_expired" || caught.code === "authentication_failed")
        ) {
          clearAuthSession();
          navigate("/auth/login?reason=expired&returnTo=%2Fapp%2Fusage");
          return;
        }
        setError(caught);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
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
        <h1>Sign in to view reconciled usage.</h1>
        <a className="button primary" href="/auth/login?returnTo=%2Fapp%2Fusage">Sign in</a>
      </main>
    );
  }

  if (!session.scopes.includes("usage:read")) {
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Permission required</p>
        <h1>Usage access is not granted.</h1>
        <p className="lede compact">This route requires the usage:read permission.</p>
        <SpaLink className="button secondary" href="/app">Return to workspace</SpaLink>
      </main>
    );
  }

  const zeroUsage = usage?.dimensions.every((dimension) => dimension.used === 0) ?? false;

  return (
    <main className="workspace-shell">
      <Navbar />
      <section className="subscription-heading">
        <div>
          <p className="eyebrow">Usage and Quotas / Usage</p>
          <h1>Current reconciled usage</h1>
          <p className="lede compact">Aggregate tenant counters from the durable usage ledger.</p>
        </div>
        <div className="page-actions">
          <SpaLink className="button secondary" href="/app/subscription">View plan</SpaLink>
          <button
            className="button primary"
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
          <strong>Usage could not be refreshed</strong>
          <p>{errorMessage(error)}</p>
          {error instanceof GraphRecApiError && error.correlationId ? (
            <small>Reference: {error.correlationId}</small>
          ) : null}
        </div>
      ) : null}

      {!usage && isLoading ? (
        <section className="subscription-loading" aria-live="polite">
          Reconciling the current UTC period…
        </section>
      ) : null}

      {usage ? (
        <>
          <section className="usage-period" aria-label="Usage period">
            <div><span>Period</span><strong>{date(usage.period_start)} – {date(usage.period_end)}</strong></div>
            <div><span>Resets</span><strong>{date(usage.reset_at)}</strong></div>
            <div><span>Last reconciled</span><strong>{timestamp(usage.last_reconciled_at)} UTC</strong></div>
          </section>
          {zeroUsage ? (
            <div className="zero-usage" role="status">
              <strong>No metered usage in this period.</strong>
              <span>All supported dimensions are reconciled at zero.</span>
            </div>
          ) : null}
          <section className="usage-grid" aria-label="Usage dimensions">
            {usage.dimensions.map((dimension) => {
              const state = stateFor(dimension);
              const percentage = dimension.limit && dimension.limit > 0
                ? Math.min(100, (dimension.used / dimension.limit) * 100)
                : 0;
              return (
                <article className={`usage-card usage-${state}`} key={dimension.type}>
                  <div className="usage-card-heading">
                    <h2>{label(dimension.type)}</h2>
                    <span>{state}</span>
                  </div>
                  <p className="usage-value">{number(dimension.used)} <small>{dimension.unit}</small></p>
                  {dimension.limit === null ? (
                    <p className="usage-detail">Informational dimension · no hard limit</p>
                  ) : (
                    <>
                      <div className="usage-progress" aria-label={`${label(dimension.type)} ${Math.round(percentage)} percent used`}>
                        <span style={{ width: `${percentage}%` }} />
                      </div>
                      <dl className="usage-stats">
                        <div><dt>Limit</dt><dd>{number(dimension.limit)}</dd></div>
                        <div><dt>Remaining</dt><dd>{number(dimension.remaining ?? 0)}</dd></div>
                      </dl>
                    </>
                  )}
                </article>
              );
            })}
          </section>
          <aside className="project-notice">
            <strong>{usage.project_defaults ? "Project-default usage limits" : "Tenant usage limits"}</strong>
            <p>Aggregate counters only. No raw customer, product, event, payment, or source-ledger data is shown.</p>
          </aside>
        </>
      ) : null}
    </main>
  );
}
