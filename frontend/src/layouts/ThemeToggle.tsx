import { useState } from 'react';
import { Button } from '../ui';
import { currentTheme, toggleTheme } from '../lib/theme';
import type { Theme } from '../lib/theme';

/**
 * Both themes are fully token-defined (§13), so this is one attribute flip.
 * It states which theme it will switch *to*, because a control labelled with
 * the current state reads as a status and gets pressed by accident.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => currentTheme());
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => setTheme(toggleTheme())}
      aria-label={theme === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme'}
    >
      {theme === 'dark' ? 'Light' : 'Dark'}
    </Button>
  );
}
