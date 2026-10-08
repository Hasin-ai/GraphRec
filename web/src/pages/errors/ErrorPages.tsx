import { Link, useLocation } from "react-router-dom";
import { useSession } from "../../hooks/useSession";
import { Page } from "../../ui/Page";
import { DefinitionList, Footnote } from "../../ui/primitives";
import { fmtDateTime } from "../../lib/format";

/** Where "start" is for whoever is looking: the tenant Overview, Platform Status, or the public home page. */
function useStartLink(): { to: string; label: string } {
  const { tenant, platform } = useSession();
  if (tenant) return { to: "/home", label: "Go to Overview" };
  if (platform) return { to: "/admin/status", label: "Go to Platform Status" };
  return { to: "/", label: "Go to GraphRec home" };
}

export function ForbiddenPage() {
  const start = useStartLink();
  return (
    <Page title="Not permitted" subtitle="Your account does not have access to this operation.">
      <Footnote>Contact your tenant administrator if you need access.</Footnote><Link className="btn btn-secondary" to={start.to}>{start.label}</Link>
    </Page>
  );
}

export function NotFoundPage() {
  const start = useStartLink();
  return (
    <Page title="Page not found" subtitle="This page doesn't exist, or you don't have access to it.">
      <Footnote>Check the address, or go back to the start page.</Footnote>
      <div>
        <Link className="btn btn-primary" to={start.to}>
          {start.label}
        </Link>
      </div>
    </Page>
  );
}

/** Reached with a correlation reference in router state after an unexpected failure. */
export function FailurePage() {
  const state = (useLocation().state as { reference?: string; at?: number } | null) ?? {};
  const start = useStartLink();
  return (
    <Page kicker="Failure" title="Something went wrong" subtitle="The request could not be completed. Quote the reference below if you contact platform support.">
      <DefinitionList
        items={[
          { label: "Error reference", value: state.reference ?? "not available", mono: true, copy: state.reference },
          { label: "Occurred at", value: fmtDateTime(state.at), mono: true },
        ]}
      />
      <Link className="btn btn-secondary" to={start.to}>{start.label}</Link>
    </Page>
  );
}
