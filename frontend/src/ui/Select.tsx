import type { SelectHTMLAttributes } from 'react';
import { FieldShell, controlClass } from './Field';

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id'> {
  label: string;
  hint?: string;
  error?: string;
  options: readonly SelectOption[];
  /** Rendered as an empty-valued first option, for "any" filters. */
  placeholder?: string;
}

export function Select({
  label,
  hint,
  error,
  options,
  placeholder,
  required,
  ...rest
}: SelectProps) {
  return (
    <FieldShell label={label} hint={hint} error={error} required={required}>
      {({ id, describedBy, invalid }) => (
        <select
          {...rest}
          id={id}
          required={required}
          className={controlClass(invalid)}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
        >
          {placeholder ? <option value="">{placeholder}</option> : null}
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </FieldShell>
  );
}
