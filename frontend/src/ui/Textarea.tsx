import type { TextareaHTMLAttributes } from 'react';
import { FieldShell, controlClass } from './Field';

export interface TextareaProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'> {
  label: string;
  hint?: string;
  error?: string;
  mono?: boolean;
}

export function Textarea({ label, hint, error, mono, required, rows = 4, ...rest }: TextareaProps) {
  return (
    <FieldShell label={label} hint={hint} error={error} required={required} mono={mono}>
      {({ id, describedBy, invalid }) => (
        <textarea
          {...rest}
          id={id}
          rows={rows}
          required={required}
          className={controlClass(invalid)}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
        />
      )}
    </FieldShell>
  );
}
