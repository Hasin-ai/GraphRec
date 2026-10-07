import { Link } from "react-router-dom";

export function FinalCta() {
  return <section className="mkt-section mkt-final" aria-labelledby="final-title">
    <div className="mkt-container">
      <div className="mkt-final-card">
        <h2 id="final-title">Start on the Free plan.</h2>
        <p>Register a tenant, activate your administrator account with the one-time setup link, and send your first events.</p>
        <div className="mkt-final-ctas">
          <Link className="btn btn-primary" to="/register">Create a tenant</Link>
          <Link to="/login">Sign in</Link>
        </div>
      </div>
    </div>
  </section>;
}
