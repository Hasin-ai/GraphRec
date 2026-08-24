import type { ButtonHTMLAttributes, ReactNode } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'title'> {
  variant?: ButtonVariant;
  size?: 'md' | 'sm';
  loading?: boolean;
  children: ReactNode;
  /**
   * Why the control cannot be used. Gate 5 disables in place and states the
   * server's reason (§13); this puts that reason on the element itself, where
   * a pointer finds it as a tooltip and a screen reader finds it as the
   * accessible description. Passing it does not disable the button — the
   * caller does that — because a reason without a disabled state is a
   * legitimate thing to render on a control that is merely dangerous.
   */
  disabledReason?: string;
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  disabled,
  disabledReason,
  children,
  className,
  ...rest
}: ButtonProps) {
  const classes = ['btn', `btn--${variant}`, size === 'sm' ? 'btn--sm' : '', className ?? '']
    .filter(Boolean)
    .join(' ');
  return (
    <button
      type="button"
      {...rest}
      className={classes}
      // A loading submit disables itself but stays on the page: §11 is explicit
      // that it "does not disappear", because a button that vanishes mid-submit
      // reads as a form that lost the click.
      disabled={disabled || loading}
      aria-disabled={disabled || loading ? true : undefined}
      aria-busy={loading || undefined}
      title={disabled && disabledReason ? disabledReason : undefined}
    >
      {loading ? <span aria-hidden="true">…</span> : null}
      {children}
    </button>
  );
}
