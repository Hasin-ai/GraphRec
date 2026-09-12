import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { auth } from "../../api";
import { isApiError } from "../../api/client";
import type { TenantRegistrationResult } from "../../api/types";
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
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TenantRegistrationResult | null>(null);
  // One key per form fill: a retry after a network failure replays instead of registering twice.
  const idempotencyKey = useMemo(() => newIdempotencyKey(), []);

  async function submit() {
    const errors: Record<string, string> = {};
    if (!name.trim()) errors.name = "Enter the registered business name.";
    if (!email.trim() || !email.includes("@")) errors.email = "Enter a valid email address.";
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      setError({ title: "Registration could not be completed", body: "Correct the highlighted field and submit again." });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await auth.registerTenant({ name: name.trim(), admin_email: email.trim().toLowerCase() }, idempotencyKey));
    } catch (caught) {
      if (isApiError(caught) && caught.status === 409) {
        setError({
          title: "This registration already exists",
          body: `A tenant named “${name.trim()}” with this administrator email was already registered. Sign in with that account, or ask your operator for a fresh setup link if it was never activated.`,
        });
        setFieldErrors({ email: "Already registered for this business." });
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
      <Page kicker="GraphRec" title="Tenant created" badge={<Tag tone="ok">{result.status}</Tag>} subtitle="The administrator account is invited. Finish setup with the one-time link below, then sign in.">
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
    <Page kicker="GraphRec" title="Register a tenant" subtitle="Creates the tenant account and its initial administrator. The registrant becomes that administrator and chooses a password on the setup page.">
      <Form onSubmit={submit} error={error} submitLabel="Create tenant" busy={busy} width={520} secondary={{ label: "Sign in instead", to: "/login" }}>
        <Field id="name" label="Business name" wide error={fieldErrors.name}>
          <TextInput id="name" value={name} onChange={setName} placeholder="Northgate Supply" autoComplete="organization" required />
        </Field>
        <Field id="email" label="Administrator email" wide error={fieldErrors.email}>
          <TextInput id="email" type="email" value={email} onChange={setEmail} placeholder="admin@company.example" autoComplete="email" required />
        </Field>
      </Form>
      <Footnote>Registering the same business and administrator email twice is reported as a conflict with the form still filled. The request carries an idempotency key, so a retry never creates a second tenant.</Footnote>
    </Page>
  );
}
