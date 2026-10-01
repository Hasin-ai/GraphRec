import { Link, useLocation } from "react-router-dom";
import { Page } from "../../ui/Page";
import { DefinitionList, Footnote } from "../../ui/primitives";
import { fmtDateTime } from "../../lib/format";

export function ForbiddenPage() {
  return (
    <Page title="Not permitted" subtitle="Your account does not have access to this operation.">
      <Footnote>Contact your tenant administrator if you need access.</Footnote><Link className="btn btn-secondary" to="/">Back to start</Link>
    </Page>
  );
}

export function NotFoundPage() {
  return (
    <Page title="Not found" subtitle="No such resource.">
      <Footnote>A resource belonging to another tenant is indistinguishable from one that does not exist.</Footnote>
      <div>
        <Link className="btn btn-secondary" to="/">
          Back to start
        </Link>
      </div>
    </Page>
  );
}

/** Reached with a correlation reference in router state after an unexpected failure. */
export function FailurePage() {
  const state = (useLocation().state as { reference?: string; at?: number } | null) ?? {};
  return (
    <Page kicker="Failure" title="Something went wrong" subtitle="The request could not be completed. Quote the reference below if you contact platform support.">
      <DefinitionList
        items={[
          { label: "Error reference", value: state.reference ?? "not available", mono: true, copy: state.reference },
          { label: "Occurred at", value: fmtDateTime(state.at), mono: true },
        ]}
      />
      <Link className="btn btn-secondary" to="/">Back to start</Link>
    </Page>
  );
}
