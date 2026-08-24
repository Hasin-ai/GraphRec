/**
 * §13: dialogs trap focus. That is implemented here and nowhere else, so no
 * caller can forget it.
 *
 * Three behaviours make up the trap: focus moves into the dialog on open,
 * Tab and Shift+Tab cycle within it, and focus returns to whatever opened it
 * on close. The third is the one usually left out, and it is the one that
 * matters most — a keyboard user who confirms a dialog and lands back at the
 * top of the document has lost the row they were working on.
 */
import { useCallback, useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { Button } from './Button';

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export interface DialogProps {
  /** Imperative, per §11: "Activate version 7", not "Confirm". */
  title: string;
  children: ReactNode;
  onClose: () => void;
  /** Omitted for a purely informational dialog, which then has only a close. */
  onConfirm?: () => void;
  confirmLabel?: string;
  confirmVariant?: 'primary' | 'danger';
  confirmDisabled?: boolean;
  cancelLabel?: string;
  busy?: boolean;
  /** 640px for forms, 480px for confirmations (§11). */
  wide?: boolean;
  /** Suppresses Esc and the scrim click, for a one-time secret that must be
   *  acknowledged rather than dismissed by accident. */
  dismissible?: boolean;
}

export function Dialog({
  title,
  children,
  onClose,
  onConfirm,
  confirmLabel = 'Confirm',
  confirmVariant = 'primary',
  confirmDisabled = false,
  cancelLabel = 'Cancel',
  busy = false,
  wide = false,
  dismissible = true,
}: DialogProps) {
  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);

  const close = useCallback(() => {
    if (dismissible) onClose();
  }, [dismissible, onClose]);

  useEffect(() => {
    opener.current = document.activeElement;
    const first = panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel.current)?.focus();
    return () => {
      if (opener.current instanceof HTMLElement) opener.current.focus();
    };
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        close();
        return;
      }
      if (event.key !== 'Tab' || !panel.current) return;
      const focusable = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) return;
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === panel.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKeyDown, true);
    return () => document.removeEventListener('keydown', onKeyDown, true);
  }, [close]);

  return (
    <div
      className="dialog__scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={wide ? 'dialog dialog--wide' : 'dialog'}
      >
        <div className="dialog__head">
          <h2>{title}</h2>
        </div>
        <div className="dialog__body">{children}</div>
        <div className="dialog__foot">
          {dismissible ? (
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              {cancelLabel}
            </Button>
          ) : null}
          {onConfirm ? (
            <Button
              variant={confirmVariant}
              onClick={onConfirm}
              loading={busy}
              disabled={confirmDisabled}
            >
              {confirmLabel}
            </Button>
          ) : (
            <Button variant="primary" onClick={onClose}>
              Close
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
