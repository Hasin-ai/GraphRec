import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { auth } from "../../api";
import { isApiError } from "../../api/client";
import type { TenantRegistrationResult } from "../../api/types";
import { setTenantSession } from "../../auth/session";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime, newIdempotencyKey } from "../../lib/format";
import { Field, Form, TextInput, type FormError } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Banner, CopyButton, DefinitionList, Footnote, Tag } from "../../ui/primitives";

/** Setup links carry the token in the URL fragment, which browsers never send to a server. */
export function setupLink(token: string): string {
  return `${window.location.origin}/setup#token=${encodeURIComponent(token)}`;
}

export function RegisterPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const navigate = useNavigate();
  const { refresh } = useSession();
  const { flash } = useToast();
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TenantRegistrationResult | null>(null);
  // One key per form fill: a retry after a network failure replays instead of registering twice.
  const attempt = useRef<{ payload: string; key: string } | null>(null);

  async function submit() {
    const errors: Record<string, string> = {};
    if (!name.trim()) errors.name = "Enter the registered business name.";
    if (!email.trim() || !email.includes("@")) errors.email = "Enter a valid email address.";
    if (password.length < 8) errors.password = "Use at least 8 characters.";
    else if (password !== confirm) errors.confirm = "The passwords do not match.";
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      setError({ title: "Registration could not be completed", body: "Correct the highlighted field and submit again." });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const input = { name: name.trim(), admin_email: email.trim().toLowerCase() };
      const payload = JSON.stringify(input);
      if (attempt.current?.payload !== payload) attempt.current = { payload, key: newIdempotencyKey() };
      const registered = await auth.registerTenant(input, attempt.current.key);
      if (!registered.setup_token) { setResult(registered); return; }   // a replay: the link was issued earlier
      try {
        // One step for the person registering: activate the administrator account with the
        // password they just chose, using the one-time token from the registration response.
        const pair = await auth.setupPassword({ setup_token: registered.setup_token, password, email: input.admin_email });
        setTenantSession(pair.email ?? input.admin_email, pair);
        refresh();
        flash(`Welcome to GraphRec. ${registered.name} is ready.`);
        navigate("/home", { replace: true });
      } catch {
        // Registration succeeded but activation did not: show the one-time setup link instead.
        setResult(registered);
      }
    } catch (caught) {
      if (isApiError(caught) && caught.status === 409) {
        // D15: show the reason the API gives for each field instead of assuming
        // that both the name and the email were already registered together.
        const mapped: Record<string, string> = {};
        for (const f of caught.fields) mapped[f.field === "admin_email" ? "email" : f.field] = f.message;
        setError({
          title: "This registration already exists",
          body: mapped.name && mapped.email ? "Both the business name and the administrator email are already in use. Sign in with your existing account, or ask your operator for a fresh setup link."
            : mapped.name ? "Choose a different business name and submit again."
            : mapped.email ? "Use a different administrator email, or sign in with your existing account."
            : "Correct the highlighted fields and submit again.",
        });
        setFieldErrors(mapped);
      } else if (isApiError(caught) && caught.code === "validation_failed") {
        setError({ title: "Registration could not be completed", body: "Correct the highlighted field and submit again." });
        const mapped: Record<string, string> = {};
        for (const f of caught.fields) mapped[f.field === "admin_email" ? "email" : f.field] = f.message;
        setFieldErrors(mapped);
      } else if (isApiError(caught) && caught.code === "rate_limit_exceeded") {
        setError({ title: "Too many registrations", body: `Try again in ${caught.retryAfterSeconds ?? "a few"} seconds.`, tone: "warn" });
      } else {
        setError({ title: "Registration could not be completed", body: "The request did not succeed. Try again shortly." });
      }
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    const link = result.setup_token ? setupLink(result.setup_token) : null;
    return (
      <Page kicker="GraphRec" title="Account created" badge={<Tag tone="ok">{result.status}</Tag>} subtitle="Your workspace exists, but the administrator account could not be activated automatically. Finish setup with the one-time link below, then sign in.">
        {link ? (
          <Banner tone="warn" title="Save this setup link now">
            It is shown once. GraphRec stores only a hash of the token; an operator can issue a new one if this link is lost.
          </Banner>
        ) : (
          <Banner tone="info" title="This registration was replayed">
            The setup link was issued with the original response and is not shown again. Ask your operator to issue a fresh setup token.
          </Banner>
        )}
        {link ? (
          <div className="snippet">
            <div className="s-head">
              <span className="s-label">Setup link</span>
              <span style={{ marginLeft: "auto" }}>
                <CopyButton value={link} label="Copy link" />
              </span>
            </div>
            <pre data-testid="setup-link">{link}</pre>
          </div>
        ) : null}
        <DefinitionList
          items={[
            { label: "Tenant", value: result.name },
            { label: "Administrator email", value: result.administrator_email, mono: true },
            { label: "Tenant identifier", value: result.id, mono: true, copy: result.id },
            { label: "Setup link expires", value: fmtDateTime(result.setup_token_expires_at), mono: true },
            { label: "Next step", value: result.next_step },
          ]}
        />
        <div className="row">
          {link ? (
            <Link className="btn btn-primary" to={`/setup#token=${encodeURIComponent(result.setup_token ?? "")}`} state={{ email: result.administrator_email }}>
              Open setup now
            </Link>
          ) : null}
          <Link className="btn btn-secondary" to="/login">
            Go to sign in
          </Link>
        </div>
      </Page>
    );
  }

  return (
    <Page kicker="GraphRec" title="Create your account" subtitle="Set up a GraphRec workspace for your business. You become its administrator and can invite developers afterwards.">
      <Form onSubmit={submit} error={error} submitLabel="Create account" busy={busy} width={460} secondary={{ label: "Already have an account? Sign in", to: "/login", variant: "link" }}>
        <Field id="name" label="Business name" wide error={fieldErrors.name}>
          <TextInput id="name" value={name} onChange={setName} placeholder="Northgate Supply" autoComplete="organization" required />
        </Field>
        <Field id="email" label="Work email" wide error={fieldErrors.email}>
          <TextInput id="email" type="email" value={email} onChange={setEmail} placeholder="you@company.example" autoComplete="email" required />
        </Field>
        <Field id="password" label="Password" wide error={fieldErrors.password} hint="At least 8 characters.">
          <TextInput id="password" type="password" value={password} onChange={setPassword} autoComplete="new-password" required />
        </Field>
        <Field id="confirm" label="Confirm password" wide error={fieldErrors.confirm}>
          <TextInput id="confirm" type="password" value={confirm} onChange={setConfirm} autoComplete="new-password" required />
        </Field>
      </Form>
      <Footnote>New accounts start on the Free plan. <Link to="/pricing">Compare plans</Link>. Invited by a colleague? Use the link they sent you instead.</Footnote>
    </Page>
  );
}
