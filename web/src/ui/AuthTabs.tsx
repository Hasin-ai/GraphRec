import { NavLink } from "react-router-dom";

/**
 * Two sign-in doors that look like one decision: workspace members (tenant
 * administrators and developers, whose role comes from their account) and
 * GraphRec platform operators, who use a separate account realm.
 */
export function AuthTabs() {
  return (
    <nav className="auth-tabs" aria-label="Who is signing in">
      <NavLink to="/login" end className={({ isActive }) => `auth-tab${isActive ? " is-active" : ""}`}>
        <span className="auth-tab-title">Workspace</span>
        <span className="auth-tab-sub">Admins &amp; developers</span>
      </NavLink>
      <NavLink to="/admin/login" end className={({ isActive }) => `auth-tab${isActive ? " is-active" : ""}`}>
        <span className="auth-tab-title">Platform operator</span>
        <span className="auth-tab-sub">GraphRec staff</span>
      </NavLink>
    </nav>
  );
}
