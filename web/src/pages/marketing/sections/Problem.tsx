export function Problem() {
  return <section className="mkt-section mkt-problem" aria-labelledby="problem-title">
    <div className="mkt-container">
      <h2 id="problem-title">Large catalogs bury the right product.</h2>
      <p>Building a recommender per shop means data pipelines, temporal modelling, evaluation, serving, isolation and quotas.</p>
      <p className="mkt-problem-answer">GraphRec is that system, shared and isolated per tenant.</p>
    </div>
  </section>;
}
