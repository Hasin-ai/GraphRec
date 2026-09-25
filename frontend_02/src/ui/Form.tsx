import { createContext, useContext, useEffect, useRef, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Banner } from "./primitives";
const FieldContext = createContext<{ invalid?: boolean; describedBy?: string; labelledBy?: string }>({});
function useFieldAttributes() {
  const field = useContext(FieldContext);
  return { 'aria-invalid': field.invalid || undefined, 'aria-describedby': field.describedBy || undefined };
}

export interface FormError {
  title: string;
  body: ReactNode;
  tone?: "danger" | "warn";
}

export function Field({
  id,
  label,
  wide,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  wide?: boolean;
  hint?: ReactNode;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className={`field${wide ? " wide" : ""}`}>
      <label id={`${id}-label`} htmlFor={id}>{label}</label>
      <FieldContext.Provider value={{ invalid: !!error, describedBy: [error ? `${id}-error` : '', hint ? `${id}-hint` : ''].filter(Boolean).join(' '), labelledBy: `${id}-label` }}>{children}</FieldContext.Provider>
      {error ? (
        <div className="err" id={`${id}-error`} role="alert">
          {error}
        </div>
      ) : null}
      {hint ? <div className="hint" id={`${id}-hint`}>{hint}</div> : null}
    </div>
  );
}

interface InputProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  mono?: boolean;
  autoComplete?: string;
  required?: boolean;
  disabled?: boolean;
  min?: number;
  max?: number;
}

export function TextInput({ id, value, onChange, type = "text", placeholder, mono, autoComplete, required, disabled, min, max }: InputProps) {
  return (
    <input
      {...useFieldAttributes()}
      className={`input${mono ? " mono" : ""}`}
      id={id}
      name={id}
      type={type}
      placeholder={placeholder}
      value={value}
      autoComplete={autoComplete}
      required={required}
      disabled={disabled}
      min={min}
      max={max}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export function TextArea({ id, value, onChange, rows = 5, placeholder, mono }: { id: string; value: string; onChange: (v: string) => void; rows?: number; placeholder?: string; mono?: boolean }) {
  return <textarea {...useFieldAttributes()} className={`input${mono ? " mono" : ""}`} id={id} name={id} rows={rows} placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />;
}

export function Select({ id, value, onChange, options }: { id: string; value: string; onChange: (v: string) => void; options: { value: string; label?: string }[] | string[] }) {
  return (
    <select {...useFieldAttributes()} className="input" id={id} name={id} value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => {
        const opt = typeof o === "string" ? { value: o, label: o } : o;
        return (
          <option key={opt.value} value={opt.value}>
            {opt.label ?? opt.value}
          </option>
        );
      })}
    </select>
  );
}

export function CheckGroup({ options, value, onChange }: { options: { value: string; label: string }[]; value: string[]; onChange: (v: string[]) => void }) {
  const field = useContext(FieldContext);
  return (
    <div className="check-group" role="group" aria-labelledby={field.labelledBy} aria-describedby={field.describedBy}>
      {options.map((o) => {
        const checked = value.includes(o.value);
        return (
          <label key={o.value}>
            <input type="checkbox" checked={checked} onChange={() => onChange(checked ? value.filter((v) => v !== o.value) : [...value, o.value])} />
            <span>
              {o.label} <span className="mono muted" style={{ fontSize: 11 }}>{o.value}</span>
            </span>
          </label>
        );
      })}
    </div>
  );
}

/**
 * A form with the prototype's shape: an inline error banner above the fields, a
 * responsive field grid, and a submit row with an optional secondary link.
 */
export function Form({
  onSubmit,
  error,
  submitLabel,
  busy,
  secondary,
  note,
  width = 720,
  children,
}: {
  onSubmit: () => void | Promise<void>;
  error?: FormError | null;
  submitLabel: string;
  busy?: boolean;
  secondary?: { label: string; to: string };
  note?: ReactNode;
  width?: number;
  children: ReactNode;
}) {
  const ref = useRef<HTMLFormElement>(null);
  const submitting = useRef(false);
  useEffect(() => { if (error) ref.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(); }, [error]);
  function handle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || submitting.current) return;
    submitting.current = true;
    void Promise.resolve(onSubmit()).finally(() => { submitting.current = false; });
  }
  return (
    <form ref={ref} className="form" aria-busy={busy || undefined} style={{ maxWidth: width }} onSubmit={handle} noValidate>
      {error ? (
        <Banner tone={error.tone ?? "danger"} title={error.title}>
          {error.body}
        </Banner>
      ) : null}
      <fieldset className="fields" disabled={busy}>{children}</fieldset>
      <div className="submit-row">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Working…" : submitLabel}
        </button>
        {secondary ? (
          <Link to={secondary.to} className="btn btn-secondary">
            {secondary.label}
          </Link>
        ) : null}
        {note ? <span className="note">{note}</span> : null}
      </div>
    </form>
  );
}
