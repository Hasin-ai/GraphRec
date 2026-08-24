/**
 * Which of the two themes is on the document.
 *
 * Both are defined entirely in `styles/tokens.css` (§13), so switching is one
 * attribute on `<html>` and nothing else. The choice is a display preference,
 * not a credential, so `localStorage` is the right home for it — unlike the
 * session, which §10.3 forbids from going there.
 */

export type Theme = 'light' | 'dark';

const KEY = 'graphrec.theme';

function stored(): Theme | null {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    // Private browsing, or storage disabled. The system preference still works.
    return null;
  }
}

/** The stored choice if there is one, otherwise what the operating system says. */
export function preferredTheme(): Theme {
  const choice = stored();
  if (choice) return choice;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset['theme'] = theme;
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    // The attribute is set either way; only the persistence is lost.
  }
}

export function currentTheme(): Theme {
  return document.documentElement.dataset['theme'] === 'dark' ? 'dark' : 'light';
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  return next;
}
