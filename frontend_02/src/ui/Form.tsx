import type { FormEvent, ReactNode } from "react";
import { Link } from "react-router-dom";
import { Banner } from "./primitives";

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
      <label htmlFor={id}>{label}</label>
      {children}
      {error ? (
        <div className="err" role="alert">
          {error}
        </div>
      ) : null}
      {hint ? <div className="hint">{hint}</div> : null}
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
  return <textarea className={`input${mono ? " mono" : ""}`} id={id} name={id} rows={rows} placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />;
}

export function Select({ id, value, onChange, options }: { id: string; value: string; onChange: (v: string) => void; options: { value: string; label?: string }[] | string[] }) {
  return (
    <select className="input" id={id} name={id} value={value} onChange={(e) => onChange(e.target.value)}>
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
  return (
    <div className="check-group">
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
  function handle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void onSubmit();
  }
  return (
    <form className="form" style={{ maxWidth: width }} onSubmit={handle} noValidate>
      {error ? (
        <Banner tone={error.tone ?? "danger"} title={error.title}>
          {error.body}
        </Banner>
      ) : null}
      <div className="fields">{children}</div>
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
