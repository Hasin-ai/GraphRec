import { useEffect, useState } from 'react';

export interface CopyFieldProps {
  value: string;
  /** What is being copied, for the button's accessible name. */
  label: string;
}

/**
 * Identifiers, credential prefixes and artifact digests are all things a
 * reader has to move somewhere else exactly, so they get a copy control rather
 * than being left to a selection that stops one character short.
 *
 * `navigator.clipboard` is absent in jsdom and on any page not served over a
 * secure origin, so its absence is a state this handles rather than a crash:
 * the value is still readable and selectable, which is what the control was
 * standing in for.
 */
export function CopyField({ value, label }: CopyFieldProps) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }

  return (
    <span className="copyfield">
      <span className="copyfield__value">{value}</span>
      <button
        type="button"
        className="copyfield__btn"
        onClick={() => void copy()}
        aria-label={`Copy ${label}`}
      >
        {copied ? 'Copied' : failed ? 'Select it' : 'Copy'}
      </button>
      <span className="visually-hidden" role="status">
        {copied ? `${label} copied to the clipboard.` : ''}
      </span>
    </span>
  );
}
