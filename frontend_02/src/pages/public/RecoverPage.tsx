import { Link } from "react-router-dom";
import { Page } from "../../ui/Page";
import { Banner, Footnote, Snippet } from "../../ui/primitives";

/**
 * The API has no self-service recovery endpoint. Rather than a form that goes
 * nowhere, this page states the supported path: an operator issues a fresh
 * one-time setup token for the account, which is accepted at /setup.
 */
export function RecoverPage() {
  return (
    <Page kicker="GraphRec" title="Recover access" subtitle="Self-service recovery is not available in this release. Access is restored by an operator issuing a new one-time setup token for the account.">
      <Banner tone="info" title="How recovery works">
        The operator runs the command below on the API host. It revokes any earlier token, prints a fresh setup link, and the link is accepted once at <span className="mono">/setup</span>.
      </Banner>
      <Snippet label="On the API host" code={"docker compose exec api python -m scripts.issue_account_setup_token admin@example.org"} />
      <div className="row">
        <Link className="btn btn-primary" to="/setup">
          I have a setup link
        </Link>
        <Link className="btn btn-secondary" to="/login">
          Back to sign in
        </Link>
      </div>
      <Footnote>The response to a recovery request never confirms whether an account exists; the operator verifies identity out of band.</Footnote>
    </Page>
  );
}
