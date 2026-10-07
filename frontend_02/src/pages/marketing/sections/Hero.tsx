import { Link } from "react-router-dom";
import { GraphIllustration } from "../../../brand/BrandMark";
import { BRAND } from "../../../marketing/copy";

export function Hero() {
  return <section className="mkt-hero" aria-labelledby="hero-title">
    <div className="mkt-container mkt-hero-inner">
      <div className="mkt-hero-copy">
        <p className="mkt-eyebrow">Recommendation platform for e-commerce</p>
        <h1 id="hero-title">{BRAND.tagline}</h1>
        <p className="mkt-lede">{BRAND.heroLede}</p>
        <div className="mkt-hero-ctas">
          <Link className="btn btn-on-dark" to="/register">Create a tenant</Link>
          <Link className="btn btn-secondary" to="/pricing">See pricing</Link>
        </div>
        <p className="mkt-hero-alt">Already have an account? <Link to="/login">Sign in</Link></p>
      </div>
      <div className="mkt-hero-visual"><GraphIllustration trail className="mkt-graph" /></div>
    </div>
  </section>;
}
