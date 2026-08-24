export interface TabDef {
  id: string;
  label: string;
}

export interface TabsProps {
  label: string;
  tabs: readonly TabDef[];
  active: string;
  onChange: (id: string) => void;
}

/**
 * Arrow keys move between tabs and only the active tab is in the tab order,
 * which is the ARIA tablist pattern. A tablist where every tab is tabbable
 * makes a keyboard user pass through all of them to reach the panel.
 */
export function Tabs({ label, tabs, active, onChange }: TabsProps) {
  function onKeyDown(event: React.KeyboardEvent) {
    const index = tabs.findIndex((tab) => tab.id === active);
    if (index < 0) return;
    const delta = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (delta === 0) return;
    event.preventDefault();
    const next = tabs[(index + delta + tabs.length) % tabs.length]!;
    onChange(next.id);
  }

  return (
    <div className="tabs" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`tab-${tab.id}`}
          aria-selected={tab.id === active}
          aria-controls={`panel-${tab.id}`}
          tabIndex={tab.id === active ? 0 : -1}
          className="tabs__tab"
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} tabIndex={0}>
      {children}
    </div>
  );
}
