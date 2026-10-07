import type { ReactNode } from "react";

/** One landing-page section: an anchor target with exactly one h2. */
export function Section({ id, title, kicker, intro, tone, children }: {
  id: string; title: ReactNode; kicker?: string; intro?: ReactNode; tone?: "alt"; children?: ReactNode;
}) {
  const headingId = `${id}-title`;
  return <section id={id} className={`mkt-section${tone ? ` ${tone}` : ""}`} aria-labelledby={headingId} tabIndex={-1}>
    <div className="mkt-container">
      <div className="mkt-section-head">
        {kicker ? <p className="mkt-kicker">{kicker}</p> : null}
        <h2 id={headingId}>{title}</h2>
        {intro ? <p>{intro}</p> : null}
      </div>
      {children}
    </div>
  </section>;
}
