/**
 * The shared shell behind `Input`, `Select` and `Textarea`.
 *
 * Label above, control, then a single slot that holds either the hint or the
 * error — never both. §11: "error replaces hint in `--danger`". Wiring the
 * control to whichever one is showing via `aria-describedby` means a screen
 * reader hears the error for the same reason a sighted reader sees it, rather
 * than hearing a hint that has been visually replaced.
 */
import { useId } from 'react';
import type { ReactNode } from 'react';

export interface FieldShellProps {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  mono?: boolean;
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode;
}

export function FieldShell({ label, hint, error, required, mono, children }: FieldShellProps) {
  const id = useId();
  const noteId = `${id}-note`;
  const note = error ?? hint;
  return (
    <div className={mono ? 'field field--mono' : 'field'}>
      <label className="field__label" htmlFor={id}>
        {label}
        {required ? (
          <>
            {' '}
            <span aria-hidden="true">*</span>
            <span className="visually-hidden">(required)</span>
          </>
        ) : null}
      </label>
      {children({ id, describedBy: note ? noteId : undefined, invalid: Boolean(error) })}
      {note ? (
        <div
          id={noteId}
          className={error ? 'field__error' : 'field__hint'}
          // Errors arrive after submit, so they have to announce themselves;
          // a hint is present from the start and must not.
          role={error ? 'alert' : undefined}
        >
          {note}
        </div>
      ) : null}
    </div>
  );
}

export function controlClass(invalid: boolean): string {
  return invalid ? 'field__control field__control--invalid' : 'field__control';
}
