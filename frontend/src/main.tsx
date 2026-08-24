import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { applyTheme, preferredTheme } from './lib/theme';

import './styles/tokens.css';
import './styles/base.css';
import './styles/primitives.css';
import './styles/layout.css';

// Before the first paint, so the page does not flash the other theme.
applyTheme(preferredTheme());

const container = document.getElementById('root');
if (!container) throw new Error('index.html is missing #root');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
