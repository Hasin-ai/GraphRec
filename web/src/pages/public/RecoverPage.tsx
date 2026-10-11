import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { auth } from "../../api";
import { isApiError } from "../../api/client";
import { useToast } from "../../hooks/useToast";
import { Field, Form, TextInput, type FormError } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Footnote } from "../../ui/primitives";

function tokenFromLocation(): string {
  return new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token") ?? "";
}

export function RecoverPage() {
  const navigate = useNavigate();
  const { flash } = useToast();
  const [linkToken] = useState(tokenFromLocation);
  const [token, setToken] = useState(linkToken);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (linkToken) window.history.replaceState(window.history.state, "", window.location.pathname);
  }, [linkToken]);

  async function submit() {
    if (!token.trim() || password.length < 8 || password !== confirm) {
      setError({ title: "Check your entries", body: "Provide the one-time token and matching passwords of at least 8 characters." });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await auth.recoverPassword({ recovery_token: token.trim(), password,
        ...(email.trim() ? { email: email.trim().toLowerCase() } : {}) });
      flash("Password changed. Sign in with your new password.");
      navigate("/login", { replace: true });
    } catch (caught) {
      if (isApiError(caught) && caught.code === "invalid_recovery_token") {
        setError({ title: "This token cannot be used", body: "It has expired, was already used, or is not valid. Ask your platform operator for a new token." });
      } else if (isApiError(caught) && caught.code === "rate_limit_exceeded") {
        setError({ title: "Too many attempts", body: `Try again in ${caught.retryAfterSeconds ?? "a few"} seconds.`, tone: "warn" });
      } else {
        setError({ title: "Recovery unavailable", body: "Check the fields or try again shortly." });
      }
    } finally {
      setBusy(false);
    }
  }

  return <Page kicker="GraphRec · account recovery" title="Reset your password" subtitle="Ask your platform operator for a one-time recovery token, then choose a new password.">
    <Form onSubmit={submit} error={error} submitLabel="Change password" busy={busy} width={460} secondary={{ label: "Back to sign in", to: "/login", variant: "link" }}>
      <Field id="recovery-token" label="Recovery token" wide>
        <TextInput id="recovery-token" type="password" value={token} onChange={setToken} mono autoComplete="off" required />
      </Field>
      <Field id="recovery-email" label="Email (optional cross-check)" wide>
        <TextInput id="recovery-email" type="email" value={email} onChange={setEmail} autoComplete="username" />
      </Field>
      <Field id="recovery-password" label="New password">
        <TextInput id="recovery-password" type="password" value={password} onChange={setPassword} autoComplete="new-password" required />
      </Field>
      <Field id="recovery-confirm" label="Confirm new password">
        <TextInput id="recovery-confirm" type="password" value={confirm} onChange={setConfirm} autoComplete="new-password" required />
      </Field>
    </Form>
    <Footnote>Tokens expire after one hour and can be used only once. Changing the password ends existing access and refresh sessions.</Footnote>
  </Page>;
}
