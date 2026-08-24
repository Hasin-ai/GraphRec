import type { InputHTMLAttributes } from 'react';
import { FieldShell, controlClass } from './Field';

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: string;
  hint?: string;
  error?: string;
  mono?: boolean;
}

export function Input({ label, hint, error, mono, required, ...rest }: InputProps) {
  return (
    <FieldShell label={label} hint={hint} error={error} required={required} mono={mono}>
      {({ id, describedBy, invalid }) => (
        <input
          {...rest}
          id={id}
          required={required}
          className={controlClass(invalid)}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
        />
      )}
    </FieldShell>
  );
}
