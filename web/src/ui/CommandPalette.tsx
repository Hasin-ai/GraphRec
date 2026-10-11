import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon, type IconName } from "./icons";

export interface CommandItem {
  id: string;
  label: string;
  to: string;
  icon: IconName;
  section: string;
  scope?: string;
  keywords?: string[];
}

const TENANT_COMMANDS: CommandItem[] = [
  { id: "home", label: "Overview", to: "/home", icon: "home", section: "Overview", keywords: ["dashboard", "kpi", "metrics"] },
  { id: "products", label: "Products", to: "/products", icon: "box", section: "Catalog", scope: "catalog:read", keywords: ["catalog", "items", "sku"] },
  { id: "sync", label: "Catalog sync", to: "/products/sync", icon: "refresh-cw", section: "Catalog", scope: "catalog:write", keywords: ["sync", "import", "batch"] },
  { id: "events", label: "Interaction Events", to: "/events/submit", icon: "activity", section: "Catalog", scope: "events:write", keywords: ["events", "stream", "interactions", "clicks", "purchases"] },
  { id: "datasets", label: "Datasets", to: "/datasets", icon: "database", section: "Catalog", scope: "training:read", keywords: ["snapshots", "training data", "splits"] },
  { id: "training", label: "Training Jobs", to: "/training", icon: "cpu", section: "Models", scope: "training:read", keywords: ["jobs", "train", "retrain", "epochs"] },
  { id: "models", label: "Model Versions", to: "/models", icon: "layers", section: "Models", scope: "models:read", keywords: ["serving", "production", "rollback", "promote"] },
  { id: "rules", label: "Recommendation Rules", to: "/recommendation-rules", icon: "sliders", section: "Models", scope: "models:read", keywords: ["boost", "bury", "filter", "pin"] },
  { id: "playground", label: "Recommendation Playground", to: "/playground", icon: "play", section: "Models", scope: "recommendations:read", keywords: ["test", "preview", "curl", "recs"] },
  { id: "integration", label: "Integration Guide", to: "/integration", icon: "plug", section: "Integrate", keywords: ["sdk", "api", "curl", "python", "docs"] },
  { id: "credentials", label: "API Credentials", to: "/credentials", icon: "key", section: "Integrate", scope: "keys:write", keywords: ["keys", "tokens", "secrets", "auth"] },
  { id: "users", label: "Team members", to: "/users", icon: "users", section: "Workspace", scope: "users:write", keywords: ["members", "roles", "invite"] },
  { id: "usage", label: "Usage & Quotas", to: "/usage", icon: "gauge", section: "Workspace", scope: "usage:read", keywords: ["billing", "limits", "capacity", "trends"] },
  { id: "audit", label: "Audit trail", to: "/audit", icon: "activity", section: "Workspace", scope: "audit:read", keywords: ["logs", "security", "activity"] },
  { id: "status", label: "Service Status", to: "/service-status", icon: "server", section: "Workspace", scope: "deployments:read", keywords: ["uptime", "health", "latency", "deployment"] },
  { id: "account", label: "Account Settings", to: "/account", icon: "user", section: "Workspace", keywords: ["profile", "password", "settings"] },
  { id: "pricing", label: "Plans & Pricing", to: "/pricing", icon: "gauge", section: "Workspace", keywords: ["upgrade", "tier", "limits"] },
];

const PLATFORM_COMMANDS: CommandItem[] = [
  { id: "p-status", label: "Platform Status", to: "/admin/status", icon: "server", section: "Platform", keywords: ["health", "system", "uptime"] },
  { id: "p-tenants", label: "Tenant Workspaces", to: "/admin/tenants", icon: "users", section: "Platform", keywords: ["tenants", "customers", "workspaces"] },
  { id: "p-plans", label: "Plans & Quotas", to: "/admin/plans", icon: "gauge", section: "Platform", keywords: ["tiers", "pricing", "limits"] },
  { id: "p-usage", label: "Platform Usage", to: "/admin/usage", icon: "gauge", section: "Platform", keywords: ["aggregate", "billing", "consumption"] },
  { id: "p-audit", label: "Failures & Audit", to: "/admin/audit", icon: "activity", section: "Platform", keywords: ["logs", "errors", "security"] },
  { id: "p-operators", label: "Platform Operators", to: "/admin/operators", icon: "users", section: "Platform", keywords: ["admins", "staff", "permissions"] },
];

export function CommandPalette({
  open,
  onClose,
  isPlatform = false,
  can = () => true,
}: {
  open: boolean;
  onClose: () => void;
  isPlatform?: boolean;
  can?: (scope: string) => boolean;
}) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputId = useId();

  const allItems = isPlatform ? PLATFORM_COMMANDS : TENANT_COMMANDS;
  const filteredItems = useMemo(() => {
    const accessible = allItems.filter(item => !item.scope || can(item.scope));
    const q = query.trim().toLowerCase();
    if (!q) return accessible;
    return accessible.filter(item => {
      if (item.label.toLowerCase().includes(q)) return true;
      if (item.section.toLowerCase().includes(q)) return true;
      if (item.to.toLowerCase().includes(q)) return true;
      if (item.keywords?.some(k => k.toLowerCase().includes(q))) return true;
      return false;
    });
  }, [allItems, can, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      const timer = setTimeout(() => inputRef.current?.focus(), 20);
      return () => clearTimeout(timer);
    }
  }, [open]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Keep selected item scrolled into view
  useEffect(() => {
    if (!listRef.current) return;
    const selectedEl = listRef.current.querySelector<HTMLElement>('[aria-selected="true"]');
    selectedEl?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  const selectItem = (item: CommandItem) => {
    onClose();
    navigate(item.to);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex(prev => (filteredItems.length ? (prev + 1) % filteredItems.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex(prev => (filteredItems.length ? (prev - 1 + filteredItems.length) % filteredItems.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filteredItems[selectedIndex]) {
        selectItem(filteredItems[selectedIndex]);
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  if (!open) return null;

  return (
    <div className="cmd-backdrop" onClick={onClose} role="presentation">
      <div
        className="cmd-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={e => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="cmd-input-row">
          <Icon name="search" size={18} className="cmd-input-icon" />
          <input
            ref={inputRef}
            id={inputId}
            type="text"
            className="cmd-input"
            placeholder={isPlatform ? "Jump to platform console routes…" : "Search routes, tools, or resources…"}
            value={query}
            onChange={e => setQuery(e.target.value)}
            aria-autocomplete="list"
            aria-controls="cmd-list"
            autoComplete="off"
            spellCheck="false"
          />
          <kbd className="cmd-esc-hint" onClick={onClose}>esc</kbd>
        </div>

        <div className="cmd-body">
          {filteredItems.length === 0 ? (
            <div className="cmd-empty">
              <p>No results found for &ldquo;{query}&rdquo;</p>
              <span className="cmd-empty-tip">Try searching for products, models, training, or keys.</span>
            </div>
          ) : (
            <ul ref={listRef} id="cmd-list" className="cmd-list" role="listbox">
              {filteredItems.map((item, index) => {
                const isSelected = index === selectedIndex;
                return (
                  <li
                    key={item.id}
                    id={`cmd-opt-${item.id}`}
                    role="option"
                    aria-selected={isSelected}
                    className={`cmd-item${isSelected ? " is-selected" : ""}`}
                    onClick={() => selectItem(item)}
                    onMouseEnter={() => setSelectedIndex(index)}
                  >
                    <span className="cmd-item-icon">
                      <Icon name={item.icon} size={16} />
                    </span>
                    <span className="cmd-item-text">
                      <span className="cmd-item-label">{item.label}</span>
                      <span className="cmd-item-path">{item.to}</span>
                    </span>
                    <span className="cmd-item-section">{item.section}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="cmd-foot">
          <span>Navigate with <kbd>↑</kbd><kbd>↓</kbd></span>
          <span>Select <kbd>↵</kbd></span>
          <span>Close <kbd>esc</kbd></span>
        </div>
      </div>
    </div>
  );
}
