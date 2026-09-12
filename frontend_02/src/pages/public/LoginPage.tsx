import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { auth } from "../../api";
import { isApiError } from "../../api/client";
import { setTenantSession } from "../../auth/session";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { Field, Form, TextInput, type FormError } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Footnote, Panel } from "../../ui/primitives";

const GENERIC: FormError = {
  title: "Sign-in failed",
  body: "The credentials supplied are not valid, or the account cannot sign in. If the problem continues, contact your tenant administrator.",
};

function safeReturn(value: unknown): string {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/admin") ? value : "/home";
}

export function LoginPage() {
  const { tenant, refresh } = useSession();
  const { flash } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);

  const returnTo = safeReturn((location.state as { from?: string } | null)?.from);
  if (tenant) return <Navigate to={returnTo} replace />;

  async function submit() {
    const normalized = email.trim().toLowerCase();
    if (!normalized || !password) {
      setError(GENERIC);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const pair = await auth.login({ email: normalized, password });
      setTenantSession(normalized, pair);
      refresh();
      flash("Signed in.");
      navigate(returnTo, { replace: true });
    } catch (caught) {
      if (isApiError(caught) && caught.code === "rate_limit_exceeded") {
        setError({ title: "Too many attempts", body: `Try again in ${caught.retryAfterSeconds ?? "a few"} seconds.`, tone: "warn" });
      } else if (isApiError(caught) && caught.code === "network_error") {
        setError({ title: "GraphRec could not be reached", body: "Check that the API is running and try again." });
      } else {
        setError(GENERIC);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page kicker="GraphRec" title="Sign in" subtitle="Tenant users sign in here. Platform operators use the separate platform realm.">
      <Form onSubmit={submit} error={error} submitLabel="Sign in" busy={busy} width={420} secondary={{ label: "Recover access", to: "/recover" }}>
        <Field id="email" label="Email" wide>
          <TextInput id="email" type="email" value={email} onChange={setEmail} placeholder="you@company.example" autoComplete="username" required />
        </Field>
        <Field id="password" label="Password" wide>
          <TextInput id="password" type="password" value={password} onChange={setPassword} autoComplete="current-password" required />
        </Field>
      </Form>
      <Panel
        title="Realms"
        body="This form resolves a tenant from the session. Platform administrators authenticate at /admin/login and resolve no tenant scope."
        dl={[
          { label: "Platform sign-in", value: <Link to="/admin/login">/admin/login</Link>, mono: true },
          { label: "Register a tenant", value: <Link to="/register">/register</Link>, mono: true },
          { label: "Finish account setup", value: <Link to="/setup">/setup</Link>, mono: true },
        ]}
      />
      <Footnote>Invalid, inactive and rate-limited attempts return the same message and never reveal whether an account exists.</Footnote>
    </Page>
  );
}
