import { useTheme } from "../hooks/useTheme";

/** Light ⇄ dark toggle used on the public pages (the console offers light/dark/system in the user menu). */
export function ThemeButton({ compact }: { compact?: boolean }) {
  const [theme, toggle] = useTheme();
  const next = theme === "light" ? "Dark" : "Light";
  return <button type="button" className={`theme-toggle${compact ? " compact" : ""}`} onClick={toggle} aria-label={`Switch to ${next.toLowerCase()} theme`} title={`Switch to ${next.toLowerCase()} theme`}>
    {theme === "light"
      ? <svg aria-hidden="true" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
      : <svg aria-hidden="true" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>}
    {compact ? null : <span>{next}</span>}
  </button>;
}
