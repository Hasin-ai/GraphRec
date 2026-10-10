import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "../ui/icons";
import { ENDPOINTS, SDK_METHODS } from "./docsData";

export interface SearchResult {
  id: string;
  category: "Guide" | "Endpoint" | "SDK Method";
  title: string;
  subtitle: string;
  url: string;
  method?: string;
}

const STATIC_ARTICLES: SearchResult[] = [
  { id: "overview", category: "Guide", title: "Overview & Core Concepts", subtitle: "Graph/sequential recommender platform architecture", url: "/docs" },
  { id: "quickstart", category: "Guide", title: "5-Minute Quickstart", subtitle: "Install SDK, ingest products & events, query recommendations", url: "/docs#quickstart" },
  { id: "auth", category: "Guide", title: "Authentication & Credentials", subtitle: "API keys, Bearer tokens, scopes matrix, multi-tenancy", url: "/docs/authentication" },
  { id: "scopes", category: "Guide", title: "Scopes & Permissions", subtitle: "catalog:write, events:write, recommendations:read", url: "/docs/authentication#scopes" },
  { id: "ref-recs", category: "Guide", title: "Recommendations API Reference", subtitle: "Real-time and session-based recommendation endpoints", url: "/docs/reference#recommendations" },
  { id: "ref-catalog", category: "Guide", title: "Catalog & Products API", subtitle: "Bulk upsert, single product management, catalog syncs", url: "/docs/reference#catalog" },
  { id: "ref-events", category: "Guide", title: "Events & Ingestion API", subtitle: "Real-time and batch interaction events submission", url: "/docs/reference#events" },
  { id: "sdk-ref", category: "Guide", title: "Python SDK Reference", subtitle: "GraphRec and AsyncGraphRec client reference & options", url: "/docs/sdk" },
  { id: "sdk-ecommerce", category: "Guide", title: "E-Commerce Helpers (CatalogSync, EventTracker)", subtitle: "Chunked catalog sync and buffered background event streaming", url: "/docs/sdk#ecommerce" },
  { id: "guides-events", category: "Guide", title: "Guide: Interaction Event Semantics", subtitle: "View, cart, purchase, rating semantics and timestamps", url: "/docs/guides#event-ingestion" },
  { id: "guides-recs", category: "Guide", title: "Guide: Choosing Recommendation Types", subtitle: "Personalized DGSR vs session vs popular fallback", url: "/docs/guides#recommendation-strategies" },
  { id: "guides-cold", category: "Guide", title: "Guide: Cold-Start Handling", subtitle: "Handling anonymous shoppers and brand new catalog items", url: "/docs/guides#cold-start" },
  { id: "guides-retries", category: "Guide", title: "Guide: Production Retries & Tracing", subtitle: "Exponential backoff, correlation IDs, and idempotent keys", url: "/docs/guides#retries-errors" },
  { id: "errors", category: "Guide", title: "Errors, Limits & Changelog", subtitle: "Standard error codes, rate limits, body limits, and history", url: "/docs/errors-and-limits" },
];

export function DocsSearchModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        if (isOpen) onClose();
      }
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const q = query.trim().toLowerCase();

  const results: SearchResult[] = [];
  if (q) {
    // 1. Guides
    for (const art of STATIC_ARTICLES) {
      if (art.title.toLowerCase().includes(q) || art.subtitle.toLowerCase().includes(q)) {
        results.push(art);
      }
    }
    // 2. Endpoints
    for (const ep of ENDPOINTS) {
      if (
        ep.path.toLowerCase().includes(q) ||
        ep.summary.toLowerCase().includes(q) ||
        ep.description.toLowerCase().includes(q)
      ) {
        results.push({
          id: ep.id,
          category: "Endpoint",
          title: ep.summary,
          subtitle: `${ep.method} ${ep.path}`,
          url: `/docs/reference#${ep.id}`,
          method: ep.method,
        });
      }
    }
    // 3. SDK Methods
    for (const sm of SDK_METHODS) {
      if (
        sm.name.toLowerCase().includes(q) ||
        sm.description.toLowerCase().includes(q) ||
        sm.signature.toLowerCase().includes(q)
      ) {
        results.push({
          id: sm.name,
          category: "SDK Method",
          title: sm.signature.split("(")[0],
          subtitle: sm.description,
          url: `/docs/sdk#${sm.name.replace(/\./g, "-")}`,
        });
      }
    }
  } else {
    results.push(...STATIC_ARTICLES.slice(0, 6));
  }

  const limitedResults = results.slice(0, 10);

  const handleSelect = (result: SearchResult) => {
    onClose();
    navigate(result.url);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % Math.max(1, limitedResults.length));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + limitedResults.length) % Math.max(1, limitedResults.length));
    } else if (e.key === "Enter" && limitedResults[selectedIndex]) {
      e.preventDefault();
      handleSelect(limitedResults[selectedIndex]);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="docs-search-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label="Search documentation">
      <div className="docs-search-modal" onClick={(e) => e.stopPropagation()}>
        <div className="docs-search-input-wrap">
          <Icon name="search" size={18} className="docs-search-icon" />
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder="Search API endpoints, SDK methods, guides..."
            className="docs-search-input"
            aria-label="Search documentation query"
          />
          <kbd className="docs-search-kbd">ESC</kbd>
        </div>

        <div className="docs-search-results">
          {limitedResults.length === 0 ? (
            <div className="docs-search-empty">No documentation found for "{query}"</div>
          ) : (
            limitedResults.map((item, idx) => (
              <div
                key={item.id + idx}
                className={`docs-search-item ${idx === selectedIndex ? "active" : ""}`}
                onClick={() => handleSelect(item)}
                onMouseEnter={() => setSelectedIndex(idx)}
              >
                <div className="docs-search-item-meta">
                  <span className={`docs-category-pill ${item.category.toLowerCase().replace(/\s+/g, "-")}`}>
                    {item.category}
                  </span>
                  {item.method && (
                    <span className={`docs-method-badge ${item.method.toLowerCase()}`}>
                      {item.method}
                    </span>
                  )}
                </div>
                <div className="docs-search-item-content">
                  <div className="docs-search-item-title">{item.title}</div>
                  <div className="docs-search-item-sub">{item.subtitle}</div>
                </div>
                <span className="docs-search-item-arrow">→</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
