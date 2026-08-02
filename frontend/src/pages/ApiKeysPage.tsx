import { useEffect, useState } from "react";
import { listApiKeys, revokeApiKey } from "../api/apiKeys";
import { GraphRecApiError, type ApiKeyResource } from "../api/types";
import { clearAuthSession, getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";
import { SpaLink } from "../components/SpaLink";
import { navigate } from "../navigation";

function date(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Never";
}

function message(error: unknown): string {
  if (!(error instanceof GraphRecApiError)) return "API-key information is temporarily unavailable.";
  if (error.code === "rate_limit_exceeded") {
    return `Too many key operations. Try again in ${error.retryAfterSeconds ?? "a few"} seconds.`;
  }
  return error.message;
}

export function ApiKeysPage() {
  const session = getAuthSession();
  const [keys, setKeys] = useState<ApiKeyResource[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pendingRevoke, setPendingRevoke] = useState<ApiKeyResource | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    if (!session || !session.scopes.includes("keys:write")) return;
    let cancelled = false;
    setIsBusy(true);
    void listApiKeys(session.access_token)
      .then((result) => {
        if (!cancelled) setKeys(result.items);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        if (caught instanceof GraphRecApiError && ["authentication_failed", "token_expired"].includes(caught.code)) {
          clearAuthSession();
          navigate("/auth/login?reason=expired&returnTo=%2Fapp%2Fintegration%2Fapi-keys");
          return;
        }
        setError(caught);
      })
      .finally(() => {
        if (!cancelled) setIsBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session]);

  if (!session || !session.scopes.includes("keys:write")) {
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Permission required</p>
        <h1>API-key management is not granted.</h1>
        <p className="lede compact">This route requires an active bearer session with keys:write.</p>
        <SpaLink className="button secondary" href="/app">Return to workspace</SpaLink>
      </main>
    );
  }

  async function confirmRevoke() {
    if (!pendingRevoke) return;
    setIsBusy(true);
    setError(null);
    try {
      const updated = await revokeApiKey(session!.access_token, pendingRevoke.id);
      setKeys((current) => current?.map((key) => (key.id === updated.id ? updated : key)) ?? [updated]);
      setPendingRevoke(null);
    } catch (caught) {
      setError(caught);
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <main className="workspace-shell">
      <Navbar />
      <section className="subscription-heading">
        <div>
          <p className="eyebrow">Integration / API Keys</p>
          <h1>Server credentials</h1>
          <p className="lede compact">Create scoped credentials without exposing secrets after their one-time view.</p>
        </div>
        <SpaLink className="button primary" href="/app/integration/api-keys/new">Create API key</SpaLink>
      </section>

      {error ? <div className="error-panel" role="alert"><strong>Key operation failed</strong><p>{message(error)}</p></div> : null}
      {isBusy && keys === null ? <section className="subscription-loading">Loading redacted credentials…</section> : null}
      {keys?.length === 0 ? (
        <section className="empty-keys" role="status">
          <h2>No API keys yet</h2>
          <p>Create a least-privilege server credential when an integration is ready.</p>
        </section>
      ) : null}
      {keys && keys.length > 0 ? (
        <section className="key-list" aria-label="API keys">
          {keys.map((key) => (
            <article className="key-card" key={key.id}>
              <div className="key-card-title">
                <div><h2>{key.name}</h2><code>{key.prefix}</code></div>
                <span className={`key-status key-${key.status}`}>{key.status}</span>
              </div>
              <dl className="key-metadata">
                <div><dt>Expires</dt><dd>{date(key.expires_at)}</dd></div>
                <div><dt>Last used</dt><dd>{key.last_used_at ? date(key.last_used_at) : "Never"}</dd></div>
                <div><dt>Rotation grace</dt><dd>{key.grace_expires_at ? date(key.grace_expires_at) : "None"}</dd></div>
              </dl>
              <ul className="scope-list compact-scopes">{key.scopes.map((scope) => <li key={scope}>{scope}</li>)}</ul>
              <div className="key-actions">
                <SpaLink className="button secondary" href={`/app/integration/api-keys/${key.id}/rotate`}>
                  Rotate
                </SpaLink>
                <button
                  className="button danger"
                  type="button"
                  disabled={key.status === "revoked" || isBusy}
                  onClick={() => setPendingRevoke(key)}
                >
                  Revoke
                </button>
              </div>
            </article>
          ))}
        </section>
      ) : null}

      {pendingRevoke ? (
        <section className="confirm-panel" role="dialog" aria-modal="true" aria-labelledby="revoke-heading">
          <h2 id="revoke-heading">Revoke {pendingRevoke.name}?</h2>
          <p><code>{pendingRevoke.prefix}</code> and any predecessor in grace will stop working immediately.</p>
          <div className="page-actions">
            <button className="button secondary" type="button" onClick={() => setPendingRevoke(null)}>Cancel</button>
            <button className="button danger" type="button" disabled={isBusy} onClick={() => void confirmRevoke()}>
              Confirm revoke
            </button>
          </div>
        </section>
      ) : null}
      <p className="session-note">Only prefixes and status metadata are retained here. Full credentials belong in server-side secret storage.</p>
    </main>
  );
}
