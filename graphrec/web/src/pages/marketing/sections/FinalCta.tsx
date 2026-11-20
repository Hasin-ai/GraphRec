import { Link } from "react-router-dom";

export function FinalCta() {
  return <section className="mkt-section mkt-final" aria-labelledby="final-title">
    <div className="mkt-container">
      <div className="mkt-final-card">
        <h2 id="final-title">Start on the Free plan.</h2>
        <p>Create your account in one step, sync your catalog and send your first events. No card, no checkout.</p>
        <div className="mkt-final-ctas">
          <Link className="btn btn-primary" to="/register">Create account</Link>
          <Link to="/login">Sign in</Link>
        </div>
      </div>
    </div>
  </section>;
}
