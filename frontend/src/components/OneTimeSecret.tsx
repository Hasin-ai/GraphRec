import { useState } from "react";
import type { ApiKeySecretResource } from "../api/types";

interface OneTimeSecretProps {
  credential: ApiKeySecretResource;
  title: string;
  onClose: () => void;
}

export function OneTimeSecret({ credential, title, onClose }: OneTimeSecretProps) {
  const [revealed, setRevealed] = useState(false);
  const [copied, setCopied] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);

  async function copySecret() {
    await navigator.clipboard.writeText(credential.secret);
    setCopied(true);
  }

  return (
    <section className="secret-panel" role="dialog" aria-modal="true" aria-labelledby="secret-heading">
      <p className="eyebrow">One-time credential</p>
      <h2 id="secret-heading">{title}</h2>
      <p>This secret will never be shown again. Store it in a server-side secret manager now.</p>
      <div className="secret-value">
        <code>{revealed ? credential.secret : `${credential.prefix}••••••••••••••••••••`}</code>
        <button className="button secondary" type="button" onClick={() => setRevealed((value) => !value)}>
          {revealed ? "Hide" : "Reveal"}
        </button>
        <button className="button secondary" type="button" onClick={() => void copySecret()}>
          {copied ? "Copied" : "Copy secret"}
        </button>
      </div>
      {credential.grace_expires_at ? (
        <p className="secret-note">The predecessor remains valid until {new Date(credential.grace_expires_at).toLocaleString()}.</p>
      ) : null}
      <label className="acknowledgement">
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => setAcknowledged(event.target.checked)}
        />
        I saved this secret and understand it cannot be recovered.
      </label>
      <button className="button primary" type="button" disabled={!acknowledged} onClick={onClose}>
        Close and purge secret
      </button>
    </section>
  );
}
