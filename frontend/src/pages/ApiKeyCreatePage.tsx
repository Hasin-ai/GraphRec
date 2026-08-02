import { useEffect, useState } from "react";
import { createApiKey } from "../api/apiKeys";
import { GraphRecApiError, type ApiKeyScope, type ApiKeySecretResource } from "../api/types";
import { clearAuthSession, getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";
import { OneTimeSecret } from "../components/OneTimeSecret";
import { SpaLink } from "../components/SpaLink";
import { navigate } from "../navigation";

const adminScopes: ApiKeyScope[] = [
  "billing:read", "usage:read", "catalog:read", "catalog:write", "events:read", "events:write",
  "training:read", "training:write", "models:read", "models:write", "models:deploy",
  "recommendations:read", "deployments:read", "metrics:read",
];
const developerScopes: ApiKeyScope[] = ["catalog:read", "catalog:write", "events:read", "events:write"];

export function ApiKeyCreatePage() {
  const session = getAuthSession();
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<ApiKeyScope[]>([]);
  const [expiry, setExpiry] = useState("");
  const [secret, setSecret] = useState<ApiKeySecretResource | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const availableScopes = session?.user_role === "tenant_developer" ? developerScopes : adminScopes;
  const dirty = Boolean(name || scopes.length || expiry) && !secret;

  useEffect(() => {
    if (!dirty) return;
    const guard = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);

  if (!session || !session.scopes.includes("keys:write")) {
    return <main className="centered-page protected-gap"><Brand /><h1>API-key creation is not granted.</h1><SpaLink className="button secondary" href="/app">Return to workspace</SpaLink></main>;
  }

  function toggleScope(scope: ApiKeyScope) {
    setScopes((current) => current.includes(scope) ? current.filter((item) => item !== scope) : [...current, scope]);
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const created = await createApiKey(session!.access_token, {
        name,
        scopes,
        ...(expiry ? { expires_at: new Date(expiry).toISOString() } : {}),
      });
      setSecret(created);
    } catch (caught) {
      if (caught instanceof GraphRecApiError && ["authentication_failed", "token_expired"].includes(caught.code)) {
        clearAuthSession();
        navigate("/auth/login?reason=expired&returnTo=%2Fapp%2Fintegration%2Fapi-keys%2Fnew");
        return;
      }
      setError(caught);
    } finally {
      setIsSubmitting(false);
    }
  }

  if (secret) {
    return <main className="centered-page secret-page"><Brand /><OneTimeSecret credential={secret} title="API key created" onClose={() => { setSecret(null); navigate("/app/integration/api-keys"); }} /></main>;
  }

  return (
    <main className="workspace-shell narrow-workspace">
      <Navbar />
      <section className="subscription-heading"><div><p className="eyebrow">Integration / API Keys / Create</p><h1>Create a scoped key</h1><p className="lede compact">Grant only what this server integration needs.</p></div></section>
      {error ? <div className="error-panel" role="alert"><strong>Key was not created</strong><p>{error instanceof GraphRecApiError ? error.message : "API-key creation is temporarily unavailable."}</p></div> : null}
      <form className="key-form" onSubmit={(event) => void submit(event)}>
        <label>Credential name<input value={name} maxLength={100} required onChange={(event) => setName(event.target.value)} placeholder="production-store" /></label>
        <fieldset>
          <legend>Scopes <span>{scopes.length}/12 selected</span></legend>
          <div className="scope-picker">
            {availableScopes.map((scope) => (
              <label key={scope}><input type="checkbox" checked={scopes.includes(scope)} disabled={!scopes.includes(scope) && scopes.length >= 12} onChange={() => toggleScope(scope)} />{scope}</label>
            ))}
          </div>
        </fieldset>
        <label>Expiry <span>Optional</span><input type="datetime-local" value={expiry} onChange={(event) => setExpiry(event.target.value)} /></label>
        <div className="least-privilege"><strong>One-time secret</strong><p>The full credential appears once after creation and is never stored by this browser.</p></div>
        <button className="button primary" type="submit" disabled={isSubmitting || !name.trim() || scopes.length === 0}>{isSubmitting ? "Creating…" : "Create API key"}</button>
      </form>
    </main>
  );
}
