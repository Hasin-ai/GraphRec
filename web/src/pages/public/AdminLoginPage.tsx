import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { platform } from "../../api";
import { isApiError } from "../../api/client";
import { setPlatformSession } from "../../auth/session";
import { useMeta } from "../../hooks/useMeta";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { Field, Form, TextInput, type FormError } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Footnote } from "../../ui/primitives";

function safeReturn(value: unknown): string {
  return typeof value === "string" && value.startsWith("/admin") ? value : "/admin/status";
}

const FAILED: FormError = { title: "Sign-in failed", body: "The credentials supplied are not valid, or the operator account cannot sign in." };

/**
 * D-04: operators sign in with their own account; roles come from the account.
 * In development the bootstrap token (PLATFORM_ADMIN_TOKEN) is also accepted;
 * in production it only creates the first operator and cannot sign in here.
 */
export function AdminLoginPage() {
  const { platform: session, refresh } = useSession();
  const { flash } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const meta = useMeta();
  const [mode, setMode] = useState<"operator" | "token">("operator");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);
  const allowToken = meta?.environment === "development";

  const returnTo = safeReturn((location.state as { from?: string } | null)?.from);
  if (session) return <Navigate to={returnTo} replace />;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      if (mode === "operator") {
        if (!email.trim() || !password) { setError(FAILED); return; }
        const issued = await platform.login(email.trim(), password);
        setPlatformSession(issued.access_token, {
          credential: "operator", email: issued.email, displayName: issued.display_name, roles: issued.roles,
          expiresAt: Date.now() + issued.expires_in * 1000,
        });
      } else {
        const presented = token.trim();
        if (!presented) { setError(FAILED); return; }
        const me = await platform.me(presented);
        setPlatformSession(presented, { credential: "bootstrap_token", roles: me.roles });
      }
      refresh();
      flash("Signed in to the operator console.");
      navigate(returnTo, { replace: true });
    } catch (caught) {
      if (isApiError(caught) && caught.code === "network_error") {
        setError({ title: "GraphRec could not be reached", body: "Check that the API is running and try again." });
      } else if (isApiError(caught) && caught.code === "rate_limit_exceeded") {
        setError({ title: "Too many attempts", body: `Try again in ${caught.retryAfterSeconds ?? "a few"} seconds.` });
      } else {
        setError(FAILED);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page kicker="GraphRec · platform" title="Platform sign-in" subtitle="Sign in with your operator account to manage tenants and platform operations.">
      <Form onSubmit={submit} error={error} submitLabel="Sign in" busy={busy} width={460} secondary={{ label: "Back to tenant sign-in", to: "/login", variant: "link" }}>
        {mode === "operator" ? <>
          <Field id="operator-email" label="Operator email" wide>
            <TextInput id="operator-email" type="email" value={email} onChange={setEmail} autoComplete="username" required />
          </Field>
          <Field id="operator-password" label="Password" wide>
            <TextInput id="operator-password" type="password" value={password} onChange={setPassword} autoComplete="current-password" required />
          </Field>
        </> : <Field id="token" label="Bootstrap token" wide hint="PLATFORM_ADMIN_TOKEN. Development only: it grants every role and is not attributed to a person.">
          <TextInput id="token" type="password" value={token} onChange={setToken} autoComplete="off" required />
        </Field>}
      </Form>
      {allowToken ? <p className="footnote">
        <button type="button" className="btn-link" onClick={() => { setMode(mode === "operator" ? "token" : "operator"); setError(null); }}>
          {mode === "operator" ? "Use the development bootstrap token instead" : "Sign in with an operator account"}
        </button>
      </p> : null}
      <Footnote>Errors are non-disclosing. Your session is kept for this browser tab only and ends after an hour; every action you take is recorded under your name.</Footnote>
    </Page>
  );
}
