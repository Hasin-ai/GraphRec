import { useState, useEffect } from "react";
import { Icon } from "../ui/icons";

export type CodeLang = "curl" | "python" | "javascript";

const STORAGE_KEY = "graphrec.docs.code_lang";

const LANG_LABELS: Record<CodeLang, string> = {
  curl: "cURL",
  python: "Python (SDK)",
  javascript: "JavaScript",
};

export interface CodeTabsProps {
  examples?: {
    curl?: string;
    python?: string;
    javascript?: string;
  };
  curl?: string;
  python?: string;
  javascript?: string;
  title?: string;
}

export function DocsCodeTabs({ examples, curl, python, javascript, title }: CodeTabsProps) {
  const codeMap: Record<CodeLang, string | undefined> = {
    curl: curl ?? examples?.curl,
    python: python ?? examples?.python,
    javascript: javascript ?? examples?.javascript,
  };

  const availableLangs = (["curl", "python", "javascript"] as CodeLang[]).filter(
    (l) => Boolean(codeMap[l])
  );

  const [lang, setLang] = useState<CodeLang>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY) as CodeLang;
      if (stored && codeMap[stored]) {
        return stored;
      }
    } catch {
      /* ignore */
    }
    return availableLangs[0] || "curl";
  });

  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && e.newValue) {
        const storedLang = e.newValue as CodeLang;
        if (codeMap[storedLang]) {
          setLang(storedLang);
        }
      }
    };
    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, [codeMap]);

  // Adjust if current lang is not in available languages
  useEffect(() => {
    if (!codeMap[lang] && availableLangs.length > 0) {
      setLang(availableLangs[0]);
    }
  }, [lang, availableLangs, codeMap]);

  const switchLang = (newLang: CodeLang) => {
    setLang(newLang);
    try {
      localStorage.setItem(STORAGE_KEY, newLang);
      window.dispatchEvent(new StorageEvent("storage", { key: STORAGE_KEY, newValue: newLang }));
    } catch {
      /* ignore */
    }
  };

  const currentCode = codeMap[lang] || codeMap.curl || Object.values(codeMap).find(Boolean) || "";

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(currentCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="docs-code-tabs">
      <div className="docs-code-header">
        {availableLangs.length > 1 ? (
          <div className="docs-lang-switcher" role="tablist" aria-label="Code language">
            {availableLangs.map((l) => (
              <button
                key={l}
                type="button"
                role="tab"
                aria-selected={lang === l}
                className={`docs-lang-btn ${lang === l ? "active" : ""}`}
                onClick={() => switchLang(l)}
              >
                {LANG_LABELS[l]}
              </button>
            ))}
          </div>
        ) : (
          title && <span className="docs-code-title">{title}</span>
        )}

        <div className="docs-code-actions">
          {availableLangs.length > 1 && title && <span className="docs-code-title">{title}</span>}
          <button
            type="button"
            className="docs-copy-btn"
            onClick={handleCopy}
            title={copied ? "Copied to clipboard!" : "Copy code"}
            aria-label="Copy code"
          >
            <Icon name={copied ? "check" : "copy"} size={13} />
            <span>{copied ? "Copied" : "Copy"}</span>
          </button>
        </div>
      </div>
      <div className="docs-code-body">
        <pre className="docs-pre" tabIndex={0}>
          <code>{currentCode}</code>
        </pre>
      </div>
    </div>
  );
}
