# GraphRec UI Component Library & Design Tokens

Production-grade developer SaaS component system for the GraphRec Console (`web/src/ui/`), inspired by modern developer platforms (Linear, Stripe, Vercel) while strictly adhering to GraphRec brand guidelines (`Palette and form specs/` and `src/brand/BrandMark.tsx`).

---

## 1. Design Token Layer (`src/styles/system.css` & `app.css`)

All colors, elevation, spacing, radii, and typography derive from CSS custom properties with full Light and Dark mode support, as well as `prefers-color-scheme` and `prefers-reduced-motion` compliance.

### Color Tokens
- **Backgrounds:** `--color-canvas`, `--color-surface`, `--color-surface-2`, `--color-surface-3`
- **Text:** `--color-text`, `--color-text-2` (secondary, ≥7:1 contrast), `--color-text-3` (tertiary, ≥4.5:1 contrast)
- **Borders:** `--color-border`, `--color-border-strong`
- **Interactive Accent:** `--color-accent` (`#5b4cdb` light / `#8b80f9` dark), `--color-accent-soft`, `--color-accent-text`, `--ring`
- **Semantic Status:**
  - Success (`--ok`, `--ok-solid`, `--ok-bg`, `--ok-line`)
  - Warning (`--warn`, `--warn-solid`, `--warn-bg`, `--warn-line`)
  - Danger (`--danger`, `--danger-solid`, `--danger-bg`, `--danger-line`)
  - Information (`--info`, `--info-solid`, `--info-bg`, `--info-line`)
  - Neutral (`--neu`, `--neu-solid`, `--neu-bg`, `--neu-line`)

### Typography & Spacing
- Base scale: 4px increments (`--space-1: 4px` through `--space-6: 32px`).
- Radius: Controls `var(--radius-md)` (6px), Cards `var(--radius-card)` (8px), Pills `var(--radius-pill)` (9999px).
- Font family: Inter / system sans with tabular numerals (`tabular-nums`) for KPIs and metrics; JetBrains Mono / monospace for IDs, tokens, and code snippets.

---

## 2. Core Primitives (`src/ui/kit.tsx`)

| Component | Description | Key Props / Features |
|---|---|---|
| `Button` | Accessible button with 4 variants (`primary`, `secondary`, `ghost`, `danger`) | `variant`, `size` (`sm`, `md`), `icon`, `loading`, `disabled` |
| `ButtonLink` | Button-styled React Router link | `to`, `variant`, `size`, `icon` |
| `Card` | Uniform bordered surface container | `title`, `description`, `actions`, `flush`, `children` |
| `SectionHeader`| Section heading with description and action | `title`, `description`, `aside`, `id` |
| `StatusPill` | Pill badge displaying system status | `tone` (`success`, `warning`, `danger`, `info`, `neutral`), `icon` |
| `StatusDot` | Compact status indicator with color dot | `tone`, `children` |
| `Progress` | Accessible metric progress bar | `value` (0–100), `tone` |
| `Alert` | Inline callout notification banner | `tone`, `title`, `compact`, `action`, `children` |
| `HelpTip` | Accessible hover/focus tooltip | `label`, `children` |
| `RelativeTime` | Auto-updating relative timestamp | `value` (ISO string), `title` |
| `CopyField` | One-click copyable read-only input | `value`, `label`, `prefix`, `secret` |
| `CodeBlock` | Syntax code snippet with copy button | `code`, `language`, `filename`, `title` |
| `StatTile` | KPI summary tile with tabular numerals | `label`, `value`, `delta`, `note`, `help` |

---

## 3. Form Controls (`src/ui/Form.tsx`)

| Component | Description | Accessibility |
|---|---|---|
| `Field` | Labeled form field container | Connects `htmlFor`, error message (`aria-invalid`, `aria-describedby`), and hints |
| `TextInput` | Single-line text input | Supports types `text`, `number`, `password`, `email` with focus ring |
| `TextArea` | Multi-line auto-wrapping text area | Supports `rows`, disabled, error states |
| `Select` | Dropdown select input | Accessible select options with labels |
| `Checkbox` | Native accessible checkbox | Checked, indeterminate, disabled states |
| `Switch` | Toggle switch | Styled iOS/Linear slider with boolean state |
| `RadioGroup`| Radio option group | Keyboard arrow navigation, option labels |

---

## 4. Layout & Navigation Primitives

- **`Page` & `PageHeader` (`src/ui/Page.tsx`):**
  Renders page title, optional kicker, breadcrumbs, action bar with last updated timestamp, and content area.
- **`CommandPalette` (`src/ui/CommandPalette.tsx`):**
  Global `⌘K` / `Ctrl+K` search modal allowing rapid keyboard-driven navigation across all tenant or platform routes and tools.
- **`Dialog` & `SecretDialog` (`src/ui/Dialog.tsx`):**
  Focus-trapping modal with `Escape` handling, backdrop click dismissal, mutation lockout (`busy`), and one-time secret copy safeguard.
- **`DataTable` & `PanelTable` (`src/ui/primitives.tsx`):**
  Responsive tables with sticky headers, tabular number formatting, empty states, and pagination support.
- **`Skeleton` (`src/ui/primitives.tsx`):**
  Shimmering placeholder rows (`@keyframes fct-shimmer`) replacing jarring layout shift spinners.
