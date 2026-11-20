import { useState, useMemo } from "react";
import { Link, useLocation } from "react-router-dom";
import { DOCS_GROUPS, ENDPOINTS, type EndpointDoc } from "../../docs/docsData";
import { DocsCodeTabs } from "../../docs/DocsCodeTabs";
import { Icon } from "../../ui/icons";

export function DocsApiReferencePage() {
  const { hash } = useLocation();
  const [selectedGroup, setSelectedGroup] = useState<string>("all");
  const [filterQuery, setFilterQuery] = useState<string>("");

  const filteredEndpoints = useMemo(() => {
    return ENDPOINTS.filter((ep) => {
      const matchesGroup = selectedGroup === "all" || ep.group === selectedGroup;
      if (!matchesGroup) return false;
      if (!filterQuery.trim()) return true;
      const q = filterQuery.toLowerCase();
      return (
        ep.path.toLowerCase().includes(q) ||
        ep.summary.toLowerCase().includes(q) ||
        ep.method.toLowerCase().includes(q) ||
        (ep.scope && ep.scope.toLowerCase().includes(q)) ||
        (ep.sdkMethod && ep.sdkMethod.toLowerCase().includes(q))
      );
    });
  }, [selectedGroup, filterQuery]);

  const endpointsByGroup = useMemo(() => {
    const groupsMap = new Map<string, EndpointDoc[]>();
    for (const group of DOCS_GROUPS) {
      groupsMap.set(group.id, []);
    }
    for (const ep of filteredEndpoints) {
      const list = groupsMap.get(ep.group) || [];
      list.push(ep);
      groupsMap.set(ep.group, list);
    }
    return groupsMap;
  }, [filteredEndpoints]);

  return (
    <div className="docs-page">
      <header className="docs-page-header">
        <div className="docs-breadcrumbs">
          <Link to="/docs">Docs</Link>
          <span className="separator">/</span>
          <span>API Reference</span>
        </div>
        <h1>REST API Reference</h1>
        <p className="lead">
          Complete, verified reference for all 85 GraphRec endpoints across recommendation inference, catalog ingestion,
          interaction tracking, model training, and tenant management.
        </p>
      </header>

      {/* Control Bar: Filter by Group & Search */}
      <div className="docs-ref-controls">
        <div className="docs-ref-group-pills" role="tablist" aria-label="API Groups">
          <button
            type="button"
            className={`docs-pill-btn ${selectedGroup === "all" ? "active" : ""}`}
            onClick={() => setSelectedGroup("all")}
          >
            All Categories ({ENDPOINTS.length})
          </button>
          {DOCS_GROUPS.map((g) => {
            const count = ENDPOINTS.filter((e) => e.group === g.id).length;
            return (
              <button
                key={g.id}
                type="button"
                className={`docs-pill-btn ${selectedGroup === g.id ? "active" : ""}`}
                onClick={() => setSelectedGroup(g.id)}
              >
                {g.title} ({count})
              </button>
            );
          })}
        </div>

        <div className="docs-ref-search-box">
          <Icon name="search" size={14} />
          <input
            type="search"
            placeholder="Filter endpoints by path, method, scope or keyword..."
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            aria-label="Filter endpoints"
          />
          {filterQuery && (
            <button
              type="button"
              className="docs-clear-btn"
              onClick={() => setFilterQuery("")}
              aria-label="Clear filter"
            >
              <Icon name="x" size={12} />
            </button>
          )}
        </div>
      </div>

      {/* Endpoint Groups */}
      <div className="docs-ref-content">
        {DOCS_GROUPS.map((group) => {
          const endpointsInGroup = endpointsByGroup.get(group.id) || [];
          if (endpointsInGroup.length === 0) return null;

          return (
            <section key={group.id} id={group.id} className="docs-section docs-ref-group-section">
              <div className="docs-ref-group-header">
                <h2>{group.title}</h2>
                <p className="docs-ref-group-desc">{group.description}</p>
              </div>

              <div className="docs-endpoints-list">
                {endpointsInGroup.map((ep) => (
                  <EndpointCard key={ep.id} ep={ep} isHighlighted={hash === `#${ep.id}`} />
                ))}
              </div>
            </section>
          );
        })}

        {filteredEndpoints.length === 0 && (
          <div className="docs-empty-state">
            <Icon name="search" size={24} />
            <p>No endpoints matched your filter criteria <code>"{filterQuery}"</code>.</p>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setSelectedGroup("all");
                setFilterQuery("");
              }}
            >
              Reset Filters
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function EndpointCard({ ep, isHighlighted }: { ep: EndpointDoc; isHighlighted: boolean }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <article
      id={ep.id}
      className={`docs-endpoint-card ${isHighlighted ? "highlighted" : ""} ${collapsed ? "is-collapsed" : ""}`}
    >
      <header className="docs-endpoint-header" onClick={() => setCollapsed(!collapsed)}>
        <div className="docs-endpoint-title-row">
          <span className={`docs-method-badge method-${ep.method.toLowerCase()}`}>{ep.method}</span>
          <code className="docs-endpoint-path">{ep.path}</code>

          <div className="docs-endpoint-badges">
            {ep.scope && <span className="docs-scope-badge" title="Required Key Scope">{ep.scope}</span>}
            {ep.auth === "none" && <span className="docs-auth-badge auth-public">Public</span>}
            {ep.auth === "apiKey" && <span className="docs-auth-badge auth-apikey">API Key</span>}
            {ep.auth === "bearer" && <span className="docs-auth-badge auth-bearer">Bearer JWT</span>}
            {ep.auth === "operator" && <span className="docs-auth-badge auth-operator">Cluster Operator</span>}
          </div>
        </div>

        <div className="docs-endpoint-summary-row">
          <p className="docs-endpoint-summary">{ep.summary || ep.description}</p>
          <button
            type="button"
            className="docs-collapse-btn"
            aria-label={collapsed ? "Expand endpoint details" : "Collapse endpoint details"}
          >
            <Icon name={collapsed ? "chevron-right" : "chevron-down"} size={14} />
          </button>
        </div>
      </header>

      {!collapsed && (
        <div className="docs-endpoint-body">
          {ep.description && ep.description !== ep.summary && (
            <p className="docs-endpoint-full-desc">{ep.description}</p>
          )}

          {ep.sdkMethod && (
            <div className="docs-sdk-link-box">
              <span className="label">Python SDK:</span>
              <Link to={`/docs/sdk#${ep.sdkMethod.replace(/[^a-zA-Z0-9_-]/g, "-")}`}>
                <code>{ep.sdkMethod}</code>
              </Link>
            </div>
          )}

          {/* Parameters Table */}
          {ep.parameters.length > 0 && (
            <div className="docs-sub-section">
              <h4>Parameters</h4>
              <div className="docs-table-wrapper">
                <table className="docs-table docs-param-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Location</th>
                      <th>Type</th>
                      <th>Required</th>
                      <th>Description</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ep.parameters.map((p) => (
                      <tr key={`${p.in}-${p.name}`}>
                        <td><code>{p.name}</code></td>
                        <td><span className="badge badge-neutral">{p.in}</span></td>
                        <td><code>{p.type}</code></td>
                        <td>
                          {p.required ? (
                            <span className="badge badge-warning">Required</span>
                          ) : (
                            <span className="badge badge-neutral">Optional</span>
                          )}
                        </td>
                        <td>{p.description || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Request Body */}
          {ep.requestBody && (
            <div className="docs-sub-section">
              <h4>Request Body (<code>{ep.requestBody.contentType}</code>)</h4>
              <p className="text-muted text-sm">{ep.requestBody.schemaSummary}</p>
              <pre className="docs-pre-schema">
                <code>{ep.requestBody.exampleJson}</code>
              </pre>
            </div>
          )}

          {/* Response Codes */}
          {ep.responses.length > 0 && (
            <div className="docs-sub-section">
              <h4>Responses</h4>
              <div className="docs-response-list">
                {ep.responses.map((r) => (
                  <div key={r.status} className="docs-response-item">
                    <div className="docs-response-header">
                      <span className={`badge ${r.status >= 200 && r.status < 300 ? "badge-success" : r.status >= 400 && r.status < 500 ? "badge-warning" : "badge-danger"}`}>
                        HTTP {r.status}
                      </span>
                      <span className="docs-response-desc">{r.description}</span>
                    </div>
                    {r.exampleJson && (
                      <pre className="docs-pre-schema">
                        <code>{r.exampleJson}</code>
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Code Examples */}
          <div className="docs-sub-section">
            <h4>Code Example</h4>
            <DocsCodeTabs
              title={`${ep.method} ${ep.path}`}
              curl={ep.examples.curl}
              python={ep.examples.python}
              javascript={ep.examples.javascript}
            />
          </div>
        </div>
      )}
    </article>
  );
}
