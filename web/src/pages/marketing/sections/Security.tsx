import type { ReactNode } from "react";
import { Icon, type IconName } from "../../../ui/icons";
import { Section } from "./Section";

const ITEMS: { icon: IconName; title: string; body: ReactNode }[] = [
  { icon: "database", title: "Tenant isolation in the database",
    body: <>Every tenant table is protected by forced PostgreSQL row-level security. The tenant comes from your credentials, never from a URL, so no request can name another tenant's data.</> },
  { icon: "key", title: "Scoped, rotatable API keys",
    body: <>Keys carry only the scopes you grant and are stored as HMAC verifiers, never in plain text. The secret is shown once; rotate with a grace period or revoke at any time.</> },
  { icon: "users", title: "Roles and a separate operator realm",
    body: <>Tenant Administrators run the workspace, including users, models and serving; Tenant Developers work with API keys, the catalog and events. Platform operators sign in to a separate realm.</> },
  { icon: "alert-octagon", title: "Errors that don't leak",
    body: <>A resource that belongs to someone else looks exactly like one that doesn't exist. Errors carry a <span className="mono">correlation_id</span>, and operator actions are kept in an audit trail.</> },
];

export function Security() {
  return <Section id="security" tone="alt" kicker="Security" title="Isolated by default"
    intro="Many shops share one GraphRec deployment. None of them can see each other.">
    <ul className="mkt-grid-2">
      {ITEMS.map(item => <li key={item.title} className="mkt-card mkt-card-row">
        <span className="mkt-icon"><Icon name={item.icon} size={20} /></span>
        <div><h3>{item.title}</h3><p>{item.body}</p></div>
      </li>)}
    </ul>
  </Section>;
}
