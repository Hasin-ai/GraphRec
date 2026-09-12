import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { platform } from "../../api";
import { isApiError } from "../../api/client";
import { setPlatformSession } from "../../auth/session";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { Field, Form, TextInput, type FormError } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Footnote } from "../../ui/primitives";

function safeReturn(value: unknown): string {
  return typeof value === "string" && value.startsWith("/admin") ? value : "/admin/status";
}

/** The platform realm authenticates with the shared PLATFORM_ADMIN_TOKEN, verified against /v1/platform/status. */
export function AdminLoginPage() {
  const { platform: session, refresh } = useSession();
  const { flash } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [token, setToken] = useState("");
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);

  const returnTo = safeReturn((location.state as { from?: string } | null)?.from);
  if (session) return <Navigate to={returnTo} replace />;

  async function submit() {
    const presented = token.trim();
    if (!presented) {
      setError({ title: "Sign-in failed", body: "The credentials supplied are not valid, or the operator account cannot sign in." });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await platform.status(presented);
      setPlatformSession(presented);
      refresh();
      flash("Signed in to the platform realm.");
      navigate(returnTo, { replace: true });
    } catch (caught) {
      if (isApiError(caught) && caught.code === "network_error") {
        setError({ title: "GraphRec could not be reached", body: "Check that the API is running and try again." });
      } else {
        setError({ title: "Sign-in failed", body: "The credentials supplied are not valid, or platform administration is disabled on this deployment." });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page kicker="GraphRec · platform" title="Platform sign-in" subtitle="A separate authentication realm. A platform operator is not a tenant user and resolves no tenant scope.">
      <Form onSubmit={submit} error={error} submitLabel="Sign in" busy={busy} width={420} secondary={{ label: "Tenant sign-in", to: "/login" }}>
        <Field id="token" label="Platform administrator token" wide hint="Configured as PLATFORM_ADMIN_TOKEN on the API. Leaving it empty there disables this realm.">
          <TextInput id="token" type="password" value={token} onChange={setToken} autoComplete="off" required />
        </Field>
      </Form>
      <Footnote>Errors are non-disclosing. The token is kept for this browser tab only and is never written to a server log by the console.</Footnote>
    </Page>
  );
}
