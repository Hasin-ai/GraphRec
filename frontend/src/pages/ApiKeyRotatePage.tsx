import { useEffect, useState } from "react";
import { getApiKey, rotateApiKey } from "../api/apiKeys";
import { GraphRecApiError, type ApiKeyResource, type ApiKeySecretResource } from "../api/types";
import { clearAuthSession, getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";
import { OneTimeSecret } from "../components/OneTimeSecret";
import { SpaLink } from "../components/SpaLink";
import { navigate } from "../navigation";

export function ApiKeyRotatePage({ keyId }: { keyId: string }) {
  const session = getAuthSession();
  const [key, setKey] = useState<ApiKeyResource | null>(null);
  const [reason, setReason] = useState("");
  const [grace, setGrace] = useState(3600);
  const [confirmed, setConfirmed] = useState(false);
  const [secret, setSecret] = useState<ApiKeySecretResource | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    if (!session || !session.scopes.includes("keys:write")) return;
    setIsBusy(true);
    void getApiKey(session.access_token, keyId)
      .then(setKey)
      .catch((caught: unknown) => {
        if (caught instanceof GraphRecApiError && ["authentication_failed", "token_expired"].includes(caught.code)) {
          clearAuthSession();
          navigate(`/auth/login?reason=expired&returnTo=${encodeURIComponent(`/app/integration/api-keys/${keyId}/rotate`)}`);
          return;
        }
        setError(caught);
      })
      .finally(() => setIsBusy(false));
  }, [keyId, session]);

  if (!session || !session.scopes.includes("keys:write")) {
    return <main className="centered-page protected-gap"><Brand /><h1>API-key rotation is not granted.</h1><SpaLink className="button secondary" href="/app">Return to workspace</SpaLink></main>;
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    setError(null);
    try {
      setSecret(await rotateApiKey(session!.access_token, keyId, { grace_period_seconds: grace, reason }));
    } catch (caught) {
      if (caught instanceof GraphRecApiError && ["authentication_failed", "token_expired"].includes(caught.code)) {
        clearAuthSession();
        navigate(`/auth/login?reason=expired&returnTo=${encodeURIComponent(`/app/integration/api-keys/${keyId}/rotate`)}`);
        return;
      }
      setError(caught);
    } finally {
      setIsBusy(false);
    }
  }

  if (secret) {
    return <main className="centered-page secret-page"><Brand /><OneTimeSecret credential={secret} title="API key rotated" onClose={() => { setSecret(null); navigate("/app/integration/api-keys"); }} /></main>;
  }

  return (
    <main className="workspace-shell narrow-workspace">
      <Navbar />
      <section className="subscription-heading"><div><p className="eyebrow">Integration / API Keys / Rotate</p><h1>Rotate credential</h1><p className="lede compact">A replacement secret will be shown exactly once.</p></div></section>
      {isBusy && !key ? <section className="subscription-loading">Loading safe key metadata…</section> : null}
      {error ? <div className="error-panel" role="alert"><strong>Rotation unavailable</strong><p>{error instanceof GraphRecApiError ? error.message : "API-key rotation is temporarily unavailable."}</p></div> : null}
      {key ? (
        <form className="key-form" onSubmit={(event) => void submit(event)}>
          <div className="rotation-target"><span>Rotating</span><strong>{key.name}</strong><code>{key.prefix}</code><span className={`key-status key-${key.status}`}>{key.status}</span></div>
          <label>Old-secret grace period in seconds<input type="number" min={0} max={86400} value={grace} onChange={(event) => setGrace(Number(event.target.value))} required /></label>
          <label>Rotation reason<textarea value={reason} maxLength={500} required onChange={(event) => setReason(event.target.value)} placeholder="Scheduled production credential rotation" /></label>
          <div className="least-privilege"><strong>No blind retries</strong><p>If the response is interrupted, inspect the changed prefix from the key list. The new secret cannot be recovered.</p></div>
          <label className="acknowledgement"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />I understand the replacement secret is shown once.</label>
          <button className="button primary" type="submit" disabled={isBusy || key.status !== "active" || Boolean(key.grace_expires_at) || !reason.trim() || !confirmed}>{isBusy ? "Rotating…" : "Rotate API key"}</button>
        </form>
      ) : null}
    </main>
  );
}
