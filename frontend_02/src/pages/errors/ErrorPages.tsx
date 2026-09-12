import { Link, useLocation } from "react-router-dom";
import { Page } from "../../ui/Page";
import { DefinitionList, Footnote } from "../../ui/primitives";
import { fmtDateTime } from "../../lib/format";

export function ForbiddenPage() {
  return (
    <Page kicker="Gate 3" title="Not permitted" subtitle="Your role or credential scope does not include this operation. There is nothing to retry here.">
      <Footnote>Permission errors are terminal by design. Choose a permitted destination from the navigation.</Footnote>
    </Page>
  );
}

export function NotFoundPage() {
  return (
    <Page kicker="Gate 4" title="Not found" subtitle="No such resource.">
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
          { label: "Occurred at", value: fmtDateTime(state.at ?? Date.now()), mono: true },
        ]}
      />
      <Footnote>No credentials, payloads or other tenants’ information appear in an error reference.</Footnote>
    </Page>
  );
}
