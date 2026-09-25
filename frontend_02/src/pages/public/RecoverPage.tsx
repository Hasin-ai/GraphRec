import { Link } from "react-router-dom";
import { Page } from "../../ui/Page";
export function RecoverPage() {
  return <Page title="Recover access" subtitle="Contact your tenant administrator or platform operator for access recovery assistance.">
    <p className="footnote">Self-service password recovery is not available. Setup links are for invited accounts and cannot reset an active account's password.</p>
    <div className="row"><Link className="btn btn-primary" to="/setup">I have a setup link</Link><Link className="btn btn-secondary" to="/login">Back to sign in</Link></div>
  </Page>;
}
