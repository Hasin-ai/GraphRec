import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { auth } from "../../api";
import { isApiError } from "../../api/client";
import { setTenantSession } from "../../auth/session";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { Field, Form, TextInput, type FormError } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Footnote } from "../../ui/primitives";

function tokenFromLocation(): string {
  return new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token") ?? "";
}

/** Accept the one-time setup token: invited -> active, then straight into the console. */
export function SetupPage() {
  const { refresh } = useSession();
  const { flash } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [linkToken] = useState(tokenFromLocation);
  const [token, setToken] = useState(linkToken);
  // Registration hands the administrator email over in router state so the session is labelled.
  const [email, setEmail] = useState((location.state as { email?: string } | null)?.email ?? "");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Keep the one-time token out of browser history once it has been read.
    if (linkToken) window.history.replaceState(window.history.state, "", window.location.pathname);
  }, [linkToken]);

  async function submit() {
    const errors: Record<string, string> = {};
    if (!token.trim()) errors.token = "Required.";
    if (password.length < 8) errors.password = "At least 8 characters.";
    if (confirm !== password) errors.confirm = "The two entries do not match.";
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      setError({ title: "Correct the highlighted field", body: "Then submit again." });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const normalized = email.trim().toLowerCase();
      const pair = await auth.setupPassword({ setup_token: token.trim(), password, ...(normalized ? { email: normalized } : {}) });
      setTenantSession(normalized || "administrator", pair);
      refresh();
      flash("Account activated.");
      navigate("/home", { replace: true });
    } catch (caught) {
      if (isApiError(caught) && caught.code === "invalid_setup_token") {
        setError({ title: "This link cannot be used", body: "It has expired, was already used, or is not valid. Ask your operator for a new setup token." });
      } else if (isApiError(caught) && caught.code === "rate_limit_exceeded") {
        setError({ title: "Too many attempts", body: `Try again in ${caught.retryAfterSeconds ?? "a few"} seconds.`, tone: "warn" });
      } else if (isApiError(caught) && caught.code === "validation_failed") {
        setError({ title: "Correct the highlighted field", body: caught.fields.map((f) => f.message).join("; ") || "The password must be at least 8 characters." });
      } else {
        setError({ title: "Account setup is temporarily unavailable", body: "Try again shortly." });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page kicker="GraphRec · account setup" title="Activate your account" subtitle="Choose the password for the invited administrator. This moves the account from invited to active and signs you in.">
      <Form onSubmit={submit} error={error} submitLabel="Activate account" busy={busy} width={440} secondary={{ label: "Back to sign in", to: "/login" }}>
        <Field id="token" label="Setup token" wide error={fieldErrors.token} hint={linkToken ? "Read from your setup link." : "Paste the token from your setup link."}>
          <TextInput id="token" value={token} onChange={setToken} mono placeholder="one-time token" autoComplete="off" required />
        </Field>
        <Field id="email" label="Email (optional cross-check)" wide>
          <TextInput id="email" type="email" value={email} onChange={setEmail} autoComplete="username" />
        </Field>
        <Field id="password" label="Password" error={fieldErrors.password}>
          <TextInput id="password" type="password" value={password} onChange={setPassword} autoComplete="new-password" required />
        </Field>
        <Field id="confirm" label="Confirm" error={fieldErrors.confirm}>
          <TextInput id="confirm" type="password" value={confirm} onChange={setConfirm} autoComplete="new-password" required />
        </Field>
      </Form>
      <Footnote>Expired, used or invalid tokens are rejected without disclosing account details. Tokens expire 24 hours after issue and are revoked when a new one is issued.</Footnote>
    </Page>
  );
}
